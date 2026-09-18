"""Cureva's own additions for Act 1 (avatar intake) — never imported by stage1/.

Copied verbatim from cureva-stage1-trd.md §6. These extend the graded contract
by addition only: PRORecord/PROExtraction/AvatarTurnResponse are new pydantic
models, not modifications to schemas.py, which stays byte-identical to the
organiser's original.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class PRORecord(BaseModel):
    """One patient-reported record, written into StudyGraph's PRO index.

    Shares the same shape every other domain follows (usubjid, a per-subject
    seq, cut_available) so PRO behaves as an ordinary tenth domain to
    StudyGraph/Atlas — nothing downstream needs to know it came from a
    conversation rather than a CRF.
    """
    domain: Literal["PRO"] = "PRO"
    usubjid: str
    seq: int                              # sequential per subject, like every other domain
    pro_type: Literal["SYMPTOM", "CONMED_MENTION", "OTHER"]
    term: str                             # normalised term
    raw_quote: str                        # required — patient's exact words (PRD FR-19)
    reported_date: date | None
    source: Literal["patient_reported"] = "patient_reported"
    transcript_ref: str                   # id of the conversation turn
    cut_available: int


class PROExtraction(BaseModel):
    """What Groq extracted from one avatar turn, before it becomes a PRORecord.

    Discarded (not written) by intake/pro_writer.py when raw_quote is empty —
    PRD FR-19 is a hard rule, not a nice-to-have.
    """
    pro_type: Literal["SYMPTOM", "CONMED_MENTION", "OTHER"]
    term: str
    raw_quote: str
    reported_date: date | None


class AvatarTurnResponse(BaseModel):
    """Groq's structured dual-output for one avatar conversation turn."""
    reply_text: str
    reply_lang: str                       # BCP-47
    gesture: Literal["idle", "listening", "concern_lean_in",
                      "explaining_gesture", "reassure_nod", "farewell_wave"]
    extracted: list[PROExtraction] = []
