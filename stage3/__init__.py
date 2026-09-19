"""Cureva Stage 3 — the Watch.

`StudyWatch` is the graded contract: a walk across the whole 12-cut period on
top of Stage 2's `ReviewCrew`, which in turn sits on Stage 1's `Atlas`. Nothing
in here re-derives a detector or re-implements a review node. Watch adds
exactly what a single cycle structurally cannot have: cross-cut history.
"""
from stage3.watch import StudyWatch

__all__ = ["StudyWatch"]
