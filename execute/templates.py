"""Act 5 — real paperwork, drafted from a decision's own evidence.

Once the medical monitor approves an escalation, something has to be *written*:
a memo to the ethics committee, a query to the site, a standing instruction for
the patient-facing avatar. This module writes it.

**Every concrete detail in an artifact comes from the decision's own evidence.**
Not one subject id, date, value, unit or visit name in the output was typed
here. The templates are f-strings over real records read back out of the graph,
and where a value genuinely is not available the text says so rather than
carrying a placeholder like `[SUBJECT]` that could be mistaken for a real one
further downstream.

`source` is always `"template_only"` at this stage. `polish.py` may produce a
`"polished"` version later, and the two are never presented as the same thing
(NFR-3).

Nothing here calls a model, touches the network, or can fail in a way that
matters: a template is string formatting over data already in hand.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas import RecordRef

log = logging.getLogger("cureva.execute.templates")

ArtifactKind = Literal["IRB_MEMO", "SITE_QUERY", "AVATAR_RULE_UPDATE"]

# ==========================================================================
# Which artifact a finding produces — a documented rule, stated once
# ==========================================================================
# The split is by **who has to do something about it**, which is the only
# question that decides what gets written:
#
#   IRB_MEMO           a governance body has to be told. Participant safety, or
#                      the integrity of who is in the trial and of the record
#                      itself. These are reportable events, not housekeeping.
#
#   SITE_QUERY         the site can resolve it by checking its own source
#                      documents. A data-quality defect: something was entered
#                      wrongly, late, in the wrong unit, or not at all.
#
#   AVATAR_RULE_UPDATE the patient is the best ongoing source. These are the
#                      two codes where what the subject themselves reports —
#                      what they are taking, and what dose they actually
#                      received — is the signal that would catch a recurrence
#                      first, so the standing rule makes Cureva's intake avatar
#                      ask about it in every subsequent conversation.
#
# A code that is not listed falls back to SITE_QUERY, because asking the site
# is the lowest-consequence honest default: it seeks information rather than
# asserting a conclusion or escalating to a body that may not need to hear it.
IRB_MEMO_CODES: frozenset[str] = frozenset({
    "HYS_LAW_CANDIDATE",        # possible drug-induced liver injury
    "SAE_MISCODED",             # a serious event not reported as serious
    "SAE_UNESCALATED",          # a serious event nobody acted on
    "EXCLUSION_VIOLATION",      # a subject who should never have been enrolled
    "INCLUSION_VIOLATION",      # ditto, from the other side of the criteria
    "DOCUMENT_TAMPERED",        # the study record itself was interfered with
})

AVATAR_RULE_CODES: frozenset[str] = frozenset({
    "PROHIBITED_CONMED",        # what the subject is taking
    "DOSING_ERROR",             # what the subject actually received
})


def artifact_kind_for(code: str) -> ArtifactKind:
    """Which artifact this finding code produces. The rule above, in code."""
    if code in IRB_MEMO_CODES:
        return "IRB_MEMO"
    if code in AVATAR_RULE_CODES:
        return "AVATAR_RULE_UPDATE"
    return "SITE_QUERY"


class ExecutionArtifact(BaseModel):
    """One drafted document, and where every fact in it came from."""

    decision_id: str
    kind: ArtifactKind
    text: str
    source: Literal["template_only", "polished"] = "template_only"
    evidence: list[RecordRef] = Field(default_factory=list)
    # --- beyond TRD 6 ---
    code: str = ""
    usubjid: str | None = None
    site: str | None = None
    cut: int = 0
    #: Real record lines quoted in the text, kept separately so `polish.py` can
    #: check a reworded draft still contains every one of them.
    facts: list[str] = Field(default_factory=list)


# ==========================================================================
# Rendering real records
# ==========================================================================
#: Columns that describe the pipeline rather than the patient. Excluded from
#: quoted evidence because they are not clinical facts and would read as noise
#: in a memo to an ethics committee.
_ADMIN_COLUMNS = {"cut_available", "corrected_at_cut"}


def _record_line(ref: RecordRef, graph: Any) -> str:
    """One cited record, rendered from its real current values.

    Read through `graph.record_value()` so a correction in force at this cut is
    applied -- quoting a superseded value in a memo would be quoting something
    that is no longer true.
    """
    if ref.domain == "DOC" or ref.document:
        where = f", {ref.section}" if ref.section else ""
        return f"{ref.document or 'document'}{where}"

    record = None
    try:
        record = graph.by_key.get((ref.domain, ref.usubjid, ref.seq))
    except Exception:                                             # noqa: BLE001
        record = None
    if record is None:
        # Honest, and deliberately not a placeholder: the citation is still
        # printed so the reader can go and look, but nothing is invented.
        return (f"{ref.domain} {ref.usubjid or '?'} seq {ref.seq} "
                f"(record not retrievable at this cut)")

    parts = []
    for key, value in record.items():
        if key.startswith("_") or key in _ADMIN_COLUMNS or key == "USUBJID":
            continue
        try:
            current = graph.record_value(record, key)
        except Exception:                                         # noqa: BLE001
            current = value
        if current in (None, ""):
            continue
        parts.append(f"{key}={current}")
    # Joined with " | ", not ", ". Real lab values in this study include the
    # European decimal comma ("177,7"), and a comma-separated list containing
    # a comma-bearing value is ambiguous to a reader and to anything parsing
    # the line afterwards. The pipe cannot occur in these values.
    detail = " | ".join(parts[:8]) or "no reportable fields"
    # DM and other one-row-per-subject domains carry no sequence number, and
    # "seq None" in a memo to an ethics committee reads as a missing value
    # rather than as a domain that has none.
    locator = f"{ref.domain} {ref.usubjid}"
    if ref.seq is not None:
        locator += f" seq {ref.seq}"
    return f"{locator}: {detail}"


def _facts(evidence: list[RecordRef], graph: Any) -> list[str]:
    return [_record_line(ref, graph) for ref in evidence]


def _bullets(facts: list[str]) -> str:
    return "\n".join(f"  - {fact}" for fact in facts) or "  - (no records cited)"


def _clause(reason: str | None) -> str:
    """A monitor's reason, fit to sit mid-sentence.

    The reasons come from the study's own table and mostly end in a full stop
    ("Noted."), so interpolating one before another full stop produces
    "Noted..". Trimmed here rather than left in a document a person reads.
    """
    text = (reason or "").strip().rstrip(".")
    return f": {text}" if text else ""


def _subject_clause(usubjid: str | None, site: str | None) -> str:
    if usubjid:
        return f"subject {usubjid}" + (f" at site {site}" if site else "")
    if site:
        return f"site {site}"
    return "the study as a whole"


# ==========================================================================
# The three templates
# ==========================================================================
def _irb_memo(*, code: str, usubjid: str | None, site: str | None, cut: int,
              rationale: str, reason: str | None, facts: list[str]) -> str:
    return f"""MEMORANDUM TO THE INSTITUTIONAL REVIEW BOARD / ETHICS COMMITTEE

Subject of report : {code} concerning {_subject_clause(usubjid, site)}
Identified at     : data cut {cut}
Status            : approved for reporting by the medical monitor

WHAT WAS FOUND
{rationale}

RECORDS THIS IS BASED ON
{_bullets(facts)}

MEDICAL MONITOR'S DECISION
The finding was escalated to the medical monitor, who approved it for
reporting. The monitor's stated reason: {reason or 'none recorded'}

WHAT IS BEING DONE
This memorandum notifies the board of the finding above. The underlying
records remain as cited; nothing in the trial data has been altered in
response to this finding. Further action is for the board to direct.

Prepared automatically by Cureva from the cited records. Every value above is
reproduced from the study data as it stood at cut {cut}; no detail has been
supplied from any other source."""


def _site_query(*, code: str, usubjid: str | None, site: str | None, cut: int,
                rationale: str, reason: str | None, facts: list[str]) -> str:
    return f"""SITE DATA QUERY

To      : site {site or '(site not identified on this finding)'}
Re      : {_subject_clause(usubjid, site)}
Raised  : data cut {cut}
Query ID: {code}

WHAT WE SEE IN THE DATA
{rationale}

THE RECORDS IN QUESTION
{_bullets(facts)}

WHAT WE ARE ASKING
Please check the source documents for the records listed above and confirm
whether the values as entered are correct. If they are correct, please reply
confirming so and describe what the source shows. If they are not, please
correct them in the next data transfer and tell us what changed.

This query was approved for sending by the medical monitor{_clause(reason)}.

No value in the trial database has been changed by Cureva. This query asks the
site to confirm or correct its own entries."""


def _avatar_rule(*, code: str, usubjid: str | None, site: str | None, cut: int,
                 rationale: str, reason: str | None, facts: list[str]) -> str:
    scope = (f"subject {usubjid}" if usubjid
             else f"every subject at site {site}" if site
             else "every subject in the study")
    topic = ("concomitant medications the subject is taking"
             if code == "PROHIBITED_CONMED"
             else "the dose the subject actually received at their last visit")
    return f"""STANDING RULE UPDATE — PATIENT INTAKE AVATAR

Applies to : {scope}
Raised at  : data cut {cut}
Origin     : {code}, approved by the medical monitor

WHY THIS RULE EXISTS
{rationale}

RECORDS BEHIND IT
{_bullets(facts)}

THE RULE
In every subsequent intake conversation with {scope}, ask about {topic} and
record the answer verbatim. Do not interpret the answer, do not reassure, and
do not advise any change — report what was said and let the reviewer decide.
If the subject reports anything inconsistent with the records above, flag the
conversation for clinical review rather than resolving it in the conversation.

The medical monitor approved this rule{_clause(reason)}.

This rule changes only what the avatar ASKS. It changes no trial data, no
detector, and no threshold anywhere in this system."""


_TEMPLATES = {
    "IRB_MEMO": _irb_memo,
    "SITE_QUERY": _site_query,
    "AVATAR_RULE_UPDATE": _avatar_rule,
}


def draft_artifact(*, decision_id: str, code: str, usubjid: str | None,
                   site: str | None, cut: int, rationale: str,
                   reason: str | None, evidence: list[RecordRef],
                   graph: Any) -> ExecutionArtifact:
    """Draft the artifact an approved decision calls for. No model involved."""
    kind = artifact_kind_for(code)
    facts = _facts(list(evidence), graph)
    text = _TEMPLATES[kind](
        code=code, usubjid=usubjid, site=site, cut=cut,
        rationale=(rationale or "").strip() or f"{code} was detected and approved.",
        reason=reason, facts=facts)
    return ExecutionArtifact(
        decision_id=decision_id, kind=kind, text=text, source="template_only",
        evidence=list(evidence), code=code, usubjid=usubjid, site=site,
        cut=cut, facts=facts)
