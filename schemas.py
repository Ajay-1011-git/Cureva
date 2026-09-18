"""Contracts shared by all three stages — the shapes the grader imports.

DO NOT MODIFY THIS FILE. The grader imports these classes from your repository
and validates every response against them. Subclass them if you want extra
fields of your own; changing the given ones breaks the contract and scores zero.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FindingCode = Literal[
    "HYS_LAW_CANDIDATE", "SAE_UNESCALATED", "SAE_MISCODED", "LAB_UNIT_MISMATCH", "DUPLICATE_SUBJECT",
    "VISIT_OUT_OF_WINDOW", "AE_BEFORE_FIRST_DOSE", "MISSING_EXPOSURE_RECORD", "INCLUSION_VIOLATION",
    "EXCLUSION_VIOLATION", "PROHIBITED_CONMED", "DOSING_ERROR", "IMPLAUSIBLE_SITE_PATTERN",
    "LATE_DATA_ENTRY", "LAB_UNIT_CORRUPTION", "DOCUMENT_TAMPERED", "NO_FINDING"]


class RecordRef(BaseModel):
    domain: str
    usubjid: str | None = None
    seq: int | None = None
    document: str | None = None
    section: str | None = None

    def key(self) -> tuple:
        return (self.domain, self.usubjid, self.seq)


class Finding(BaseModel):
    code: str
    usubjid: str | None = None
    site: str | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    rationale: str
    evidence: list[RecordRef] = Field(default_factory=list)
    confidence: float = 0.8
    protocol_version: int | None = None

    def fingerprint(self) -> str:
        return f"{self.code}|{self.usubjid or ''}|{self.site or ''}|{','.join(str(e.seq) for e in self.evidence[:2])}"


class Question(BaseModel):
    id: str
    kind: Literal["count", "lookup", "finding", "trap"]
    text: str
    params: dict[str, Any] = Field(default_factory=dict)
    cut: int | None = None


class Answer(BaseModel):
    question_id: str
    answer: Any
    text: str = ""
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[RecordRef] = Field(default_factory=list)
    confidence: float = 0.8
    steps_used: int = 0
    tokens_used: int = 0


class QueryOut(BaseModel):
    id: str
    usubjid: str
    domain: str
    seq: int | None
    text: str
    status: str
    response: str | None = None


class EscalationOut(BaseModel):
    id: str
    code: str
    usubjid: str | None
    site: str | None
    summary: str
    decision: str | None
    reason: str | None


class ReviewReport(BaseModel):
    cut: int
    protocol_version: int
    findings: list[Finding]
    escalations: list[EscalationOut]
    queries: list[QueryOut]
    deviations: list[Finding]
    trace: list[dict]
    tokens_used: int = 0
    duration_ms: int = 0


class Decision(BaseModel):
    id: str
    cut: int
    action: str
    code: str
    usubjid: str | None = None
    site: str | None = None
    evidence: list[RecordRef] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    rationale: str
    tier: str = "fast"


class Explanation(BaseModel):
    decision_id: str
    what: str
    evidence: list[RecordRef]
    evidence_lines: list[str]
    alternatives: list[str]
    why: str
    consistent_with_trace: bool = True


class KRI(BaseModel):
    site: str
    deviation_rate: float
    query_rate: float
    late_entry_score: float
    implausibility: float
    sae_rate: float
    risk: float


class SurveillanceReport(BaseModel):
    period: str
    cuts: list[int]
    decisions: list[Decision]
    escalations: list[EscalationOut]
    kris: list[KRI]
    signals: list[Finding]
    budget: dict
    markdown: str
