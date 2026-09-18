"""Act 3 — the Tribunal's data shapes.

Copied from `cureva-stage2-trd.md` 6. Three personas argue a contested
finding: each proposes a verdict alone (Round 1), then sees the other two and
cross-examines (Round 2), then every claim faces a deterministic, zero-LLM
evidence check (Round 3).

`TribunalTranscript.ran` is always present and always meaningful. A transcript
that was skipped says so, with a reason, rather than arriving as an absence the
UI has to guess about -- the difference between "three reviewers agreed" and
"the Tribunal never ran" is exactly the thing a judge must not have to infer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas import RecordRef

Persona = Literal["SAFETY", "CLINICAL_OPS", "REGULATORY"]

PERSONAS: tuple[Persona, ...] = ("SAFETY", "CLINICAL_OPS", "REGULATORY")


class PersonaVerdict(BaseModel):
    persona: Persona
    finding_id: str
    verdict: Literal["ESCALATE", "MONITOR"]
    reasoning: str
    cited_evidence: list[RecordRef] = Field(default_factory=list)


class CrossExamChallenge(BaseModel):
    target_persona: Persona
    claim_challenged: str
    rebuttal: str


class CrossExamResponse(BaseModel):
    persona: Persona
    finding_id: str
    challenges: list[CrossExamChallenge] = Field(default_factory=list)
    revised_verdict: Literal["ESCALATE", "MONITOR"] | None = None


class DiscardedClaim(BaseModel):
    persona: Persona
    claim: str
    reason_discarded: str


class Arbitration(BaseModel):
    finding_id: str
    surviving_claims: list[str] = Field(default_factory=list)
    discarded_claims: list[DiscardedClaim] = Field(default_factory=list)
    final_verdict: Literal["ESCALATE", "MONITOR"]
    method: Literal["deterministic_evidence_check"] = "deterministic_evidence_check"


class TribunalTranscript(BaseModel):
    finding_id: str
    round1: list[PersonaVerdict] = Field(default_factory=list)
    round2: list[CrossExamResponse] = Field(default_factory=list)
    round3: Arbitration | None = None
    ran: bool = False
    skip_reason: str | None = None
    tokens_used: int = 0
    duration_ms: int = 0
