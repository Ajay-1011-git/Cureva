"""Act 5 — the paperwork a decision actually produces.

Template-first by design. `templates.py` drafts every artifact from the
decision's own evidence with no model involved at all; `polish.py` is an
optional, budget-ledgered rewording pass on top that may change prose and may
never change a fact.
"""
from execute.templates import ExecutionArtifact, artifact_kind_for, draft_artifact

__all__ = ["ExecutionArtifact", "artifact_kind_for", "draft_artifact"]
