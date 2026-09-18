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
from intake.patient_context import build as build_patient_context
from intake.red_flags import escalation_sentence, screen as screen_red_flags
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
#: Findings already present in the study, seeded once at startup so the graph
#: on /atlas shows the real picture from the first page load rather than an
#: empty box. A conversation then ADDS to this, which is the point — the demo
#: is "here is what the data already says, now watch a patient add to it".
def _seed_finding_graph() -> int:
    """Run every registered detector once and observe the results."""
    seeded = 0
    for code in sorted(_atlas.detectors):
        try:
            answer = _atlas.answer(Question(id=f"seed-{code}", kind="finding",
                                            text="", params={"code": code}))
            seeded += len(_finding_graph.observe_all(answer.findings, cut=_graph.cut))
        except Exception as exc:                      # noqa: BLE001
            log.warning("seeding %s failed: %s", code, exc)
    return seeded


_SEEDED = _seed_finding_graph()
log.info("finding graph seeded with %d nodes", _SEEDED)

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
    #: What `audio_b64` actually is. A browser's MediaRecorder produces webm
    #: or mp4 depending on the engine; Sarvam rejects an upload whose declared
    #: type does not match the bytes, so the client sends what it recorded
    #: rather than letting the server assume wav.
    audio_mime: str | None = None


class AvatarTurnHTTPResponse(BaseModel):
    #: What the system actually heard, when the turn came in as audio. The
    #: page shows this back to the patient — a transcription that misheard
    #: you is the single most confusing failure in a voice interface, and
    #: hiding it behind "(spoken)" makes it undebuggable during a live demo.
    transcript: str | None = None
    reply_text: str
    reply_lang: str
    gesture: str
    reply_audio_b64: str | None = None
    extracted: list[dict] = []
    pro_written: list[str] = []
    #: Reportable symptoms detected in this turn, each with why it is
    #: reportable. The page shows these; they are not a diagnosis.
    red_flags: list[dict] = []
    degraded: bool = False              # not in TRD §5's literal shape, but the
                                        # frontend needs SOME way to show the
                                        # degraded-mode indicator TRD §8 requires


# ------------------------------------------------------------------ routes
@app.post("/api/atlas/ask", response_model=Answer)
def ask(question: Question) -> Answer:
    """Direct pass-through to Atlas.answer() — manual testing and demo scripting.

    Any findings a finding/trap-kind question turns up are also observed into
    the session's FindingGraph (PRD §4.1: Act 2's graph is built from Atlas's
    own findings output). Wrapped so a FindingGraph hiccup never breaks the
    actual answer being returned — TRD §8's isolation rule applies to graph/
    exactly as it does to intake/.
    """
    answer = _atlas.answer(question)
    try:
        if answer.findings:
            _finding_graph.observe_all(answer.findings, cut=_graph.cut)
    except Exception as exc:                          # noqa: BLE001
        log.warning("finding-graph observe failed: %s", exc)
    return answer


@app.get("/api/atlas/patient360/{usubjid}")
def patient360(usubjid: str) -> dict:
    return _graph.patient360(usubjid)


@app.get("/api/atlas/subjects")
def subjects() -> list[dict]:
    """Every enrolled subject, for the /atlas subject picker.

    "Subject" on that page is who the avatar is speaking to — a real person in
    the study whose records the conversation will add to — so the picker needs
    enough context to choose meaningfully (site, arm, demographics, and how
    many findings already sit against them), not just an id to type.
    """
    findings_per_subject: dict[str, int] = {}
    for node in _finding_graph.nodes.values():
        if node.usubjid:
            findings_per_subject[node.usubjid] = findings_per_subject.get(node.usubjid, 0) + 1

    out = []
    for r in _graph.records("DM", cut=_graph.cut):
        usubjid = r["USUBJID"]
        out.append({
            "usubjid": usubjid,
            "site": _graph.site_for(usubjid),
            "arm": r.get("ARM"),
            "age": r.get("AGE"),
            "sex": r.get("SEX"),
            "country": r.get("COUNTRY"),
            "findings": findings_per_subject.get(usubjid, 0),
            "pro_records": len(_graph.by_usubjid_domain.get((usubjid, "PRO"), [])),
        })
    out.sort(key=lambda s: s["usubjid"])
    return out


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
                patient_text, detected_lang = sarvam.transcribe(
                    audio_bytes, content_type=req.audio_mime)
                lang_hint = lang_hint or detected_lang
                if not patient_text.strip():
                    # Transcription succeeded but heard nothing usable (silence,
                    # a stray tap). Say so rather than sending an empty string
                    # to Groq and getting a confused reply back.
                    return AvatarTurnHTTPResponse(
                        transcript="",
                        reply_text="I didn't catch that — could you say it again?",
                        reply_lang="en-IN", gesture="listening",
                        reply_audio_b64=None, extracted=[], pro_written=[],
                        degraded=False)
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
        # Give the model this subject's actual chart, so it interviews like
        # someone who has read it rather than a generic assistant. Wrapped:
        # a context-building failure must not cost us the turn.
        try:
            chart = build_patient_context(
                _graph, req.usubjid or "", finding_graph=_finding_graph)
        except Exception as exc:                      # noqa: BLE001
            log.warning("patient context failed for %s: %s", req.usubjid, exc)
            chart = None
        try:
            turn = groq.turn(patient_text, lang_hint=lang_hint,
                             patient_context=chart)
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
    # Deterministic safety screen over what the patient actually said, plus
    # the terms the model normalised it into. This runs independently of the
    # model's own judgement: the prompt does ask it to escalate red flags and
    # it usually does, but "usually" is the wrong reliability for the one
    # behaviour where a miss matters, and the same sentence was observed
    # escalating on one call and not the next.
    red_flags = screen_red_flags(patient_text, *[e.term for e in turn.extracted])
    if red_flags:
        sentence = escalation_sentence(red_flags)
        # Don't say it twice if the model already escalated on its own.
        if "study doctor" not in turn.reply_text.lower():
            turn = turn.model_copy(update={
                "reply_text": turn.reply_text.rstrip() + sentence,
                "gesture": "concern_lean_in"})

    subject_id = req.usubjid or "DEMO-SUBJECT"
    written = write_extractions(_graph, subject_id, turn.extracted,
                                transcript_ref=f"turn-{int(time.time()*1000)}",
                                cut_available=_graph.cut or 1)
    pro_written = [f"PRO:{subject_id}:{r.seq}" for r in written]

    # Put what the patient just said onto the Act 2 graph. The study's own
    # findings are seeded at startup, so this is the part of the picture a
    # conversation actually changes — and the page draws these differently
    # so "what the data already said" and "what this person just added" are
    # never confused for each other.
    for record in written:
        try:
            _finding_graph.observe_pro_record(record.model_dump(mode="json"),
                                              cut=_graph.cut)
        except Exception as exc:                      # noqa: BLE001
            log.warning("could not graph PRO record: %s", exc)

    # After a turn that names a real subject, re-check that subject against
    # the detectors answerable from a single snapshot — this is what makes
    # the demo's own causal narrative ("avatar hears something -> a graph
    # node appears") concrete: it observes real Atlas.answer() findings for
    # the subject the conversation is actually about, the same mechanism
    # /api/atlas/ask uses. Never raises into this response.
    if written and subject_id != "DEMO-SUBJECT":
        for code in ("HYS_LAW_CANDIDATE", "AE_BEFORE_FIRST_DOSE", "PROHIBITED_CONMED",
                     "VISIT_OUT_OF_WINDOW", "DOSING_ERROR"):
            try:
                q = Question(id=f"turn-scan-{code}", kind="finding", text="",
                            params={"code": code, "usubjid": subject_id})
                a = _atlas.answer(q)
                if a.findings:
                    _finding_graph.observe_all(a.findings, cut=_graph.cut)
            except Exception as exc:                    # noqa: BLE001
                log.warning("post-turn finding scan failed for %s: %s", code, exc)

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
        transcript=patient_text if req.audio_b64 is not None else None,
        reply_text=turn.reply_text, reply_lang=turn.reply_lang, gesture=turn.gesture,
        reply_audio_b64=reply_audio_b64,
        extracted=[e.model_dump(mode="json") for e in turn.extracted],
        pro_written=pro_written, degraded=degraded, red_flags=red_flags,
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


# ==========================================================================
# The review cycle — T2.18. Four routes, per TRD §5.
# ==========================================================================
#
# One ReviewCrew per process, built lazily. Lazy because constructing it parses
# the organiser's response files, and the server must still start and serve
# /api/atlas/* on a machine where those are missing.
#
# It runs in "defer" mode: escalations are raised and held PENDING for a person
# to answer on the review page. That is the only way PENDING is reachable at
# all — study.escalate() always replies inline — and it is what makes the human
# gate a gate rather than a read-only list. The graded path is unaffected; it
# constructs its own crew with the default "auto" mode.
_crew = None
_crew_error: str | None = None


def _get_crew():
    global _crew, _crew_error
    if _crew is None and _crew_error is None:
        try:
            from stage2 import ReviewCrew
            _crew = ReviewCrew(DATA_DIR, _atlas, tribunal=True, tribunal_budget=1,
                               human_gate="defer")
        except Exception as exc:                      # noqa: BLE001
            _crew_error = f"{type(exc).__name__}: {exc}"
            log.error("review crew unavailable: %s", _crew_error)
    return _crew


class RunCycleRequest(BaseModel):
    cut: int
    protocol_version: int


class DecisionRequest(BaseModel):
    decision: str


def _crew_or_503():
    crew = _get_crew()
    if crew is None:
        raise HTTPException(status_code=503,
                            detail=f"review cycle unavailable: {_crew_error}")
    return crew


def _escalation_payload(record, crew) -> dict:
    """An escalation plus the finding evidence a person needs to judge it."""
    finding = next((v.finding for v in crew.last_verdicts
                    if v.finding_id == record.finding_id), None)
    return {
        "escalation_id": record.escalation_id,
        "finding_id": record.finding_id,
        "code": record.code,
        "usubjid": record.usubjid,
        "site": record.site,
        "summary": record.summary,
        "state": record.state,
        "decision": record.decision,
        "reason": record.reason,
        "raised_cycle": record.raised_cycle,
        "raised_cut": record.raised_cut,
        "resolved_cycle": record.resolved_cycle,
        "clarify_count": record.clarify_count,
        "send_failed": record.send_failed,
        "severity": finding.severity if finding else None,
        "evidence": [e.model_dump() for e in finding.evidence] if finding else [],
        "has_tribunal": record.finding_id in crew.transcripts,
    }


@app.post("/api/monitor/run-cycle")
def run_cycle(req: RunCycleRequest) -> dict:
    """Run one review cycle and return the real ReviewReport."""
    crew = _crew_or_503()
    report = crew.run_cycle(cut=req.cut, protocol_version=req.protocol_version)
    # The report is returned as-is; the verdict split rides alongside it,
    # because ReviewReport has nowhere to carry escalation-worthy vs
    # watch-only and the page needs to show that distinction.
    return {
        "report": report.model_dump(mode="json"),
        "verdicts": [
            {"finding_id": v.finding_id, "code": v.finding.code,
             "usubjid": v.finding.usubjid, "site": v.finding.site,
             "severity": v.finding.severity, "escalate": v.escalate,
             "rule": v.rule, "tribunal_ran": v.tribunal_ran}
            for v in crew.last_verdicts
        ],
        "memory": crew.memory.sizes(),
        "cycle": crew.memory.cycle_number,
    }


@app.get("/api/monitor/tribunal/{finding_id}")
def tribunal_transcript(finding_id: str) -> dict:
    """That finding's full three-round transcript.

    A finding the Tribunal never ran on gets an explicit `ran: false` with a
    reason — never a bare 404, which reads as a broken page rather than as the
    honest answer that no deliberation took place.
    """
    crew = _crew_or_503()
    transcript = crew.transcripts.get(finding_id)
    if transcript is None:
        return {"finding_id": finding_id, "ran": False,
                "skip_reason": ("no deliberation was run for this finding — it was "
                                "either watch-only, or outside this cycle's budget"),
                "round1": [], "round2": [], "round3": None}
    return transcript.model_dump(mode="json")


@app.post("/api/monitor/tribunal/{finding_id}/run")
def run_tribunal(finding_id: str) -> dict:
    """Deliberate on one finding, now, because someone asked.

    The cycle's own budget is deliberately small — six network calls per
    finding against a token-per-minute ceiling means a whole-cycle
    deliberation is not affordable. But a person looking at one escalation
    and wanting the argument for *that* one is exactly the case worth
    spending a deliberation on, so it is available on demand.

    Never raises into the response: a failure comes back as ran:false with
    the real reason, the same shape a skipped deliberation has.
    """
    crew = _crew_or_503()
    verdict = next((v for v in crew.last_verdicts if v.finding_id == finding_id), None)
    if verdict is None:
        raise HTTPException(status_code=404,
                            detail=f"no finding {finding_id} in the last cycle — "
                                   f"run a cycle first")
    try:
        import tribunal
        # Longer than the cycle's budget on purpose. Inside run_cycle the
        # timeout exists to stop a network call delaying a graded result; here
        # a person has asked for this specific argument and is waiting for it,
        # so the tradeoff is the other way round. The free tier's ceiling is
        # tokens per minute, and a richer prompt spends more of them, so a
        # first attempt inside a spent window needs room to get through.
        transcript = tribunal.deliberate(_atlas, verdict.finding, finding_id,
                                         crew.graph.cut, timeout=45.0)
    except Exception as exc:                          # noqa: BLE001
        log.warning("on-demand deliberation failed for %s: %s", finding_id, exc)
        return {"finding_id": finding_id, "ran": False,
                "skip_reason": f"{type(exc).__name__}: {exc}",
                "round1": [], "round2": [], "round3": None}
    crew.transcripts[finding_id] = transcript
    if transcript.ran:
        verdict.tribunal_ran = True
    return transcript.model_dump(mode="json")


@app.get("/api/monitor/escalations")
def escalations(state: str | None = "PENDING") -> dict:
    """Current escalations. Defaults to PENDING — the human gate's worklist."""
    crew = _crew_or_503()
    wanted = None if (state or "").upper() in ("", "ALL") else state
    records = crew.escalation_view(wanted)
    counts: dict[str, int] = {}
    for record in crew.memory.escalations.values():
        counts[record.state] = counts.get(record.state, 0) + 1
    return {
        "state": wanted or "ALL",
        "counts": counts,
        "escalations": [_escalation_payload(r, crew) for r in records[:200]],
    }


class BulkDecisionRequest(BaseModel):
    decision: str
    escalation_ids: list[str] | None = None
    # With no explicit list, apply to every escalation currently in this state.
    # A judge clearing 170 pending items one click at a time is not a demo of
    # anything except patience.
    all_in_state: str | None = None
    limit: int = 500


@app.post("/api/monitor/escalations/bulk")
def decide_bulk(req: BulkDecisionRequest) -> dict:
    """Apply one decision to many escalations.

    Each one still goes through crew.decide(), which is the same
    _apply_decision the node uses — so a bulk CLARIFY really does read the
    graph and resubmit for every item, rather than taking a shortcut the
    single-item path does not take. Slower, and correct.

    One failure does not abandon the rest: each result is reported
    individually, so a partial success is visible as a partial success.
    """
    crew = _crew_or_503()
    decision = (req.decision or "").upper()
    if decision not in ("APPROVED", "REJECTED", "CLARIFY"):
        raise HTTPException(status_code=400,
                            detail=f"decision must be APPROVED, REJECTED or CLARIFY "
                                   f"— got {req.decision!r}")

    ids = req.escalation_ids
    if not ids:
        state = (req.all_in_state or "PENDING").upper()
        ids = [r.escalation_id for r in crew.escalation_view(state)]
    ids = ids[:max(0, req.limit)]

    applied, failed = [], []
    for escalation_id in ids:
        try:
            record = crew.decide(escalation_id, decision)
            applied.append({"escalation_id": escalation_id, "state": record.state,
                            "clarify_count": record.clarify_count})
        except KeyError:
            failed.append({"escalation_id": escalation_id, "error": "not found"})
        except Exception as exc:                      # noqa: BLE001
            failed.append({"escalation_id": escalation_id,
                           "error": f"{type(exc).__name__}: {exc}"})

    counts: dict[str, int] = {}
    for record in crew.memory.escalations.values():
        counts[record.state] = counts.get(record.state, 0) + 1
    return {"decision": decision, "requested": len(ids),
            "applied": len(applied), "failed": len(failed),
            "results": applied[:50], "errors": failed[:50], "counts": counts}


@app.post("/api/monitor/reset")
def reset_cycle() -> dict:
    """Forget every previous cycle. Demo control, not part of TRD §5.

    Cross-cycle memory works: escalations already answered in an earlier run
    are never raised again, so a second cycle over the same cut correctly
    leaves the human gate empty. That is the property the whole layer is
    graded on — and it means a rehearsed demo has nothing pending to show
    unless memory is cleared first.

    So this exists to reset the demo, not to work around the guarantee. It
    wipes the in-process crew and its snapshot; the next run-cycle starts
    from nothing.
    """
    global _crew, _crew_error
    import shutil
    from pathlib import Path as _Path

    _crew, _crew_error = None, None
    state = _Path("state")
    removed = []
    for target in (state / "memory_snapshot.json", state / "trace"):
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
            removed.append(str(target))
    return {"status": "reset", "removed": removed}


@app.post("/api/monitor/escalations/{escalation_id}")
def decide_escalation(escalation_id: str, req: DecisionRequest) -> dict:
    """Route a human's decision into HUMAN GATE's real state handling.

    Not a UI-only stub: this calls the same `_apply_decision` the node calls,
    so CLARIFY really does read the graph and resubmit, and a rejection really
    does close the escalation without changing the finding.
    """
    crew = _crew_or_503()
    decision = (req.decision or "").upper()
    if decision not in ("APPROVED", "REJECTED", "CLARIFY"):
        raise HTTPException(status_code=400,
                            detail=f"decision must be APPROVED, REJECTED or CLARIFY "
                                   f"— got {req.decision!r}")
    try:
        record = crew.decide(escalation_id, decision)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"no escalation {escalation_id}")
    return _escalation_payload(record, crew)
