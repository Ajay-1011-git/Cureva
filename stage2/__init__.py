"""Cureva Stage 2 — the Monitor.

`ReviewCrew` is the graded contract: a repeatable six-node review cycle over
Stage 1's `Atlas`. Nothing in here re-derives a detector; every finding comes
back through `Atlas.answer()`.
"""
from stage2.crew import ReviewCrew

__all__ = ["ReviewCrew"]
