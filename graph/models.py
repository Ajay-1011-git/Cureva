"""Cureva's own additions for Act 2 (finding graph) — never imported by stage1/.

Copied verbatim from cureva-stage1-trd.md §6.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas import RecordRef


class FindingNode(BaseModel):
    finding_id: str
    code: str                             # one of schemas.FindingCode
    usubjid: str | None = None
    site: str | None = None
    evidence: list[RecordRef] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)   # e.g. ["AE","CM","PRO"]
    cut_available: int


class FindingEdge(BaseModel):
    from_finding_id: str
    to_finding_id: str
    relation: Literal["SHARED_PROTOCOL_SECTION", "SAME_DRUG_CLASS",
                       "TEMPORAL_PROXIMITY", "SAME_AMENDMENT"]
    weight: float
