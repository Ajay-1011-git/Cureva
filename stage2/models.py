"""Cureva-owned models for Stage 2.

The organiser's `ReviewReport`, `EscalationOut`, `QueryOut`, `Finding` and
`RecordRef` are imported from `schemas.py`, never redefined here. What this
module adds is the state and trace vocabulary Stage 2 owns: the trace line
Stage 3's `explain()` will read, and the memory that makes a second cycle over
the same cut a no-op.

Shapes follow `cureva-stage2-trd.md` §6. Three fields differ from that document
and each difference is a consequence of what the organiser's starter code
actually provides -- see `docs/stage2-contract-audit.md`:

* `CrewMemorySnapshot.queries_raised` is keyed "domain:usubjid:seq", not
  "domain:usubjid:seq:field". `study.query_site()` takes exactly those three
  arguments and `RecordRef` has no field attribute (audit §3).
* `CrewMemorySnapshot.sae_unescalated_watch` maps a watch key to the *cut* it
  was first seen unescalated at, not the cycle number. The reason is in
  `stage2/crew.py`'s SAE_UNESCALATED section: counting cycles would make a
  repeat cycle over the same cut raise a new escalation, which is precisely
  what the idempotency requirement forbids.
* `CrewMemorySnapshot.query_records` is additive, and holds the `QueryOut` for
  every query ever raised. Without it a repeat cycle's `ReviewReport.queries`
  would come back empty, which reads as "no queries exist" rather than the
  truth, "no *new* queries were needed".
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from schemas import QueryOut, RecordRef

NodeName = Literal["DETECT", "MEDICAL_REVIEW", "DATA_MANAGER",
                   "COMPLIANCE", "HUMAN_GATE", "EXECUTE"]

DecisionType = Literal[
    "finding_detected", "escalation_raised", "escalation_resolved",
    "query_raised", "query_skipped_duplicate", "deviation_flagged",
    "tribunal_verdict", "tribunal_skipped",
    # Cureva additions. Each names a decision the six nodes genuinely make and
    # that FR-18 therefore requires a line for -- a verdict that never reaches
    # the human gate, and an escalation deliberately not re-raised, are both
    # decisions. Without these two the trace would silently omit the reasoning
    # behind most of a cycle's monitor-only findings.
    "verdict_assigned", "escalation_skipped_duplicate",
]


class TraceEntry(BaseModel):
    """One decision, written to disk the moment it is made.

    This is the format Stage 3's `explain()` reads. It is finalized here, per
    PRD G5 -- no shape change is acceptable after this stage ships.
    """

    trace_id: str
    cycle: int
    cut: int
    protocol_version: int
    node: NodeName
    decision_type: DecisionType
    finding_id: str | None = None
    escalation_id: str | None = None
    evidence: list[RecordRef] = Field(default_factory=list)
    summary: str
    timestamp: datetime
    duration_ms: int


class EscalationRecord(BaseModel):
    """One escalation's state, across every cycle it survives.

    `PENDING` is reachable two ways and neither is the passage of time: an
    escalation awaiting a human decision on `/monitor`, and a `study.escalate()`
    call that raised. The organiser's `escalate()` always answers inline, so a
    cycle-raised escalation is normally resolved in the cycle that raised it --
    see `docs/stage2-contract-audit.md` §2 for why the PRD's reading of
    `PENDING` could not be implemented as written.
    """

    escalation_id: str
    finding_id: str
    code: str
    usubjid: str | None = None
    site: str | None = None
    summary: str = ""
    state: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    decision: str | None = None
    reason: str | None = None
    raised_cycle: int
    raised_cut: int
    resolved_cycle: int | None = None
    clarify_count: int = 0
    # True when escalate() raised and the escalation is tracked but unsent.
    # NFR-2: the finding stays represented rather than being silently lost, and
    # a failed attempt stays distinguishable from a genuinely pending one.
    send_failed: bool = False


class CrewMemorySnapshot(BaseModel):
    """The whole of cross-cycle memory, as written to disk after every cycle."""

    cycle_number: int = 0
    queries_raised: list[str] = Field(default_factory=list)
    query_records: dict[str, QueryOut] = Field(default_factory=dict)
    escalations: dict[str, EscalationRecord] = Field(default_factory=dict)
    subject_flags: dict[str, int] = Field(default_factory=dict)
    site_flags: dict[str, int] = Field(default_factory=dict)
    sae_unescalated_watch: dict[str, int] = Field(default_factory=dict)
