"""FastAPI backend — exposes Stage 1 over HTTP per cureva-stage1-trd.md §5.

Imports stage1 (graded, network-free) + intake + graph (Cureva additions).
Never the other direction: stage1/atlas.py never imports this module.

Every Sarvam/Groq call in the avatar-turn chain is wrapped so a failure there
degrades to TRD §8's fallback path — never a 500 the frontend can't recover
from.
"""
from __future__ import annotations

import base64
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"), override=False)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from schemas import Answer, Question
from stage1.atlas import Atlas, StudyGraph

from graph.finding_graph import FindingGraph
from intake.groq_client import GroqAvatarClient, GroqUnavailable
from intake.models import AvatarTurnResponse, PROExtraction
from intake.pro_writer import write_extractions
from intake.sarvam_client import SarvamClient, SarvamUnavailable
from intake.sarvam_pool import NoSarvamKeysConfigured

log = logging.getLogger("cureva.webapp")

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")

app = FastAPI(title="Cureva — Stage 1 (Atlas)")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------- state
# One shared StudyGraph/Atlas per process — build() once at startup, never
# per-request (TRD §7). One FindingGraph per process too: this demo runs a
# single live session, per TRD §5 ("current accumulated state for this demo
# session").
_graph = StudyGraph(DATA_DIR)
_graph.build(cut=None)
_atlas = Atlas(_graph)
_finding_graph = FindingGraph(_graph)

# External clients: constructed lazily and cached, so a missing/invalid key
# fails once (at first use) rather than crashing the whole server at import
# time — the server must start and serve /api/atlas/ask even with zero
# working external credentials.
_sarvam: SarvamClient | None = None
_sarvam_error: str | None = None
_groq: GroqAvatarClient | None = None
_groq_error: str | None = None


def _get_sarvam() -> SarvamClient | None:
    global _sarvam, _sarvam_error
    if _sarvam is not None:
        return _sarvam
    if _sarvam_error is not None:
        return None
    try:
        _sarvam = SarvamClient()
        return _sarvam
    except NoSarvamKeysConfigured as exc:
        _sarvam_error = str(exc)
        log.warning("Sarvam unavailable: %s", exc)
        return None


def _get_groq() -> GroqAvatarClient | None:
    global _groq, _groq_error
    if _groq is not None:
        return _groq
    if _groq_error is not None:
        return None
    try:
        _groq = GroqAvatarClient()
        return _groq
    except GroqUnavailable as exc:
        _groq_error = str(exc)
        log.warning("Groq unavailable: %s", exc)
        return None


# ------------------------------------------------------------- request models
class AvatarTurnRequest(BaseModel):
    audio_b64: str | None = None
    text: str | None = None
    lang_hint: str | None = None
    #: Not in TRD §5's literal request shape, but needed to know which
    #: subject a PRO record belongs to. Optional; defaults to a placeholder
    #: demo subject id that can never collide with a real USUBJID.
    usubjid: str | None = None


class AvatarTurnHTTPResponse(BaseModel):
    reply_text: str
    reply_lang: str
    gesture: str
    reply_audio_b64: str | None = None
    extracted: list[dict] = []
    pro_written: list[str] = []
    degraded: bool = False              # not in TRD §5's literal shape, but the
                                        # frontend needs SOME way to show the
                                        # degraded-mode indicator TRD §8 requires


# ------------------------------------------------------------------ routes
@app.post("/api/atlas/ask", response_model=Answer)
def ask(question: Question) -> Answer:
    """Direct pass-through to Atlas.answer() — manual testing and demo scripting."""
    return _atlas.answer(question)


@app.get("/api/atlas/patient360/{usubjid}")
def patient360(usubjid: str) -> dict:
    return _graph.patient360(usubjid)


@app.get("/api/atlas/graph-stats")
def graph_stats() -> dict:
    """StudyGraph.build()'s dict, verbatim, for the UI to display build stats."""
    return _graph.stats


@app.get("/api/atlas/finding-graph")
def finding_graph() -> dict:
    """Current accumulated finding-graph state for this demo session.

    Never a 500 on a clustering edge case (TRD §8) — FindingGraph.snapshot()
    itself degrades to empty lists rather than raising.
    """
    try:
        return _finding_graph.snapshot()
    except Exception as exc:                          # noqa: BLE001
        log.warning("finding-graph snapshot failed: %s", exc)
        return {"nodes": [], "edges": [], "clusters": [], "centrality": {}}


@app.post("/api/atlas/avatar-turn", response_model=AvatarTurnHTTPResponse)
def avatar_turn(req: AvatarTurnRequest) -> AvatarTurnHTTPResponse:
    """Sarvam transcribe (if audio) -> Groq turn -> PRO writer -> Sarvam speak.

    Exactly one of audio_b64/text is expected from the client. Every external
    call is wrapped: a Sarvam or Groq failure anywhere in this chain degrades
    to TRD §8's fallback rather than raising a 500 the frontend can't recover
    from. `degraded=True` on the response is the visible indicator TRD §8/
    TNFR-5 requires — the frontend must never let a degraded state look
    identical to a working one.
    """
    if req.audio_b64 is None and req.text is None:
        raise HTTPException(400, "exactly one of audio_b64/text is required")

    degraded = False
    lang_hint = req.lang_hint

    # -- 1. transcribe, if audio was sent
    if req.audio_b64 is not None:
        sarvam = _get_sarvam()
        if sarvam is None:
            degraded = True
            patient_text = req.text or ""       # frontend is expected to have
                                                 # swapped to text-only already
        else:
            try:
                audio_bytes = base64.b64decode(req.audio_b64)
                patient_text, detected_lang = sarvam.transcribe(audio_bytes)
                lang_hint = lang_hint or detected_lang
            except SarvamUnavailable as exc:
                log.warning("Sarvam STT failed: %s", exc)
                degraded = True
                patient_text = req.text or ""
    else:
        patient_text = req.text or ""

    # -- 2. Groq dual-output turn
    groq = _get_groq()
    if groq is None:
        degraded = True
        # TRD §8: "the raw text is still written as a PROExtraction with
        # pro_type='OTHER' via a simple keyword pass" — this is that path,
        # taken when Groq itself has no key configured at all.
        keyword_extraction = (
            [PROExtraction(pro_type="OTHER", term=patient_text[:80],
                          raw_quote=patient_text, reported_date=None)]
            if patient_text.strip() else [])
        turn = AvatarTurnResponse(
            reply_text="Let me note that down.", reply_lang="en-IN",
            gesture="listening", extracted=keyword_extraction)
    else:
        try:
            turn = groq.turn(patient_text, lang_hint=lang_hint)
        except GroqUnavailable as exc:
            log.warning("Groq turn failed: %s", exc)
            degraded = True
            turn = AvatarTurnResponse(
                reply_text="Let me note that down.", reply_lang="en-IN",
                gesture="listening", extracted=[])

    # -- 3. write PRO records (subject id is out of scope for this endpoint's
    # contract in TRD §5 — a real deployment would carry it from session
    # state; here it's accepted as an optional field the frontend can send,
    # defaulting to a placeholder id that never collides with a real subject)
    subject_id = req.usubjid or "DEMO-SUBJECT"
    written = write_extractions(_graph, subject_id, turn.extracted,
                                transcript_ref=f"turn-{int(time.time()*1000)}",
                                cut_available=_graph.cut or 1)
    pro_written = [f"PRO:{subject_id}:{r.seq}" for r in written]

    # -- 5. speak the reply
    reply_audio_b64 = None
    sarvam = _get_sarvam()
    if sarvam is not None:
        try:
            audio = sarvam.speak(turn.reply_text, lang=turn.reply_lang)
            reply_audio_b64 = base64.b64encode(audio).decode("ascii")
        except SarvamUnavailable as exc:
            log.warning("Sarvam TTS failed: %s", exc)
            degraded = True
    else:
        degraded = True

    return AvatarTurnHTTPResponse(
        reply_text=turn.reply_text, reply_lang=turn.reply_lang, gesture=turn.gesture,
        reply_audio_b64=reply_audio_b64,
        extracted=[e.model_dump(mode="json") for e in turn.extracted],
        pro_written=pro_written, degraded=degraded,
    )


@app.get("/api/health")
def health() -> dict:
    """Not in TRD §5 — a small addition so the demo can confirm the server is
    up and which external services are configured, without a full avatar turn."""
    return {
        "status": "ok",
        "graph": _graph.stats.get("nodes"),
        "sarvam_configured": _get_sarvam() is not None,
        "groq_configured": _get_groq() is not None,
    }
