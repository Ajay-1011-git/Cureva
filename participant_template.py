"""The three classes the grader imports. Copy into your repo and fill them in.

    stage1/atlas.py   ->  StudyGraph, Atlas
    stage2/crew.py    ->  ReviewCrew      (imports stage1)
    stage3/watch.py   ->  StudyWatch      (imports stage2)

Keep the class names, the method names and the signatures. Everything inside
them is yours. The grader does roughly this:

    atlas = Atlas(StudyGraph("hackathon-data"))
    atlas.graph.build(cut=None)
    for q in hidden_questions:
        answer = atlas.answer(q)          # validated against schemas.Answer
"""
from __future__ import annotations

from schemas import Answer, Explanation, Question, ReviewReport, SurveillanceReport


# ============================================================ STAGE 1
class StudyGraph:
    def __init__(self, data_dir: str):
        """data_dir is the hackathon-data folder."""
        raise NotImplementedError

    def build(self, cut: int | None = None) -> dict:
        """Build the graph from the CSVs. Return at least:
        {"nodes": int, "edges": int, "subjects": int, "cut": int|None, "ms": int}
        Write this dict to graph_stats.json for your submission."""
        raise NotImplementedError

    def patient360(self, usubjid: str) -> dict:
        """Everything about one subject, in one object. Shape is yours —
        your interface renders it; the grader does not parse it."""
        raise NotImplementedError


class Atlas:
    def __init__(self, graph: StudyGraph):
        raise NotImplementedError

    def answer(self, question: Question) -> Answer:
        """Answer one question.

        Remember:
          - every RecordRef in `evidence` must exist AND support your claim
          - answer within 120 seconds per question
          - when the honest answer is nothing, return an empty list, not a guess
          - set `confidence` honestly; confident and wrong is penalised
        """
        raise NotImplementedError


# ============================================================ STAGE 2
class ReviewCrew:
    def __init__(self, data_dir: str, atlas: Atlas):
        raise NotImplementedError

    def run_cycle(self, cut: int, protocol_version: int) -> ReviewReport:
        """One review cycle over one data cut.

        The ReviewReport must carry findings, escalations, queries, deviations
        and a trace with one entry per node decision, each naming the node and
        the evidence. A node that leaves no trace entry is treated as not run.

        Running the same cut twice must raise ZERO new queries and ZERO new
        escalations — memory is tested directly.
        """
        raise NotImplementedError


# ============================================================ STAGE 3
class StudyWatch:
    def __init__(self, data_dir: str, crew: ReviewCrew):
        raise NotImplementedError

    def run_period(self, cuts=range(1, 13)) -> SurveillanceReport:
        """Walk the cuts unattended. Must finish inside the time budget —
        degrade rather than crash or go silent."""
        raise NotImplementedError

    def explain(self, decision_id: str) -> Explanation:
        """Explain one decision: what, the evidence records, the alternatives
        rejected, and why. Read it from your trace, not from a reconstruction —
        judges compare it against the trace on screen."""
        raise NotImplementedError
