"""Cureva Stage 1 — the graded contract: StudyGraph and Atlas.

This module is deliberately network-free. It imports only the standard library,
pydantic (via `schemas`) and `study` — never `intake/`, `graph/`, `requests` or
an LLM SDK. `run_local_harness.py` must be able to import and score it with no
internet access at all (cureva-stage1-trd.md §2).

Stub as of T1.0; filled in from T1.3 onward.
"""
from __future__ import annotations

from schemas import Answer, Question


class StudyGraph:
    def __init__(self, data_dir: str):
        raise NotImplementedError("T1.3")

    def build(self, cut: int | None = None) -> dict:
        raise NotImplementedError("T1.4")

    def patient360(self, usubjid: str) -> dict:
        raise NotImplementedError("T1.5")


class Atlas:
    def __init__(self, graph: StudyGraph):
        raise NotImplementedError("T1.6")

    def answer(self, question: Question) -> Answer:
        raise NotImplementedError("T1.6")
