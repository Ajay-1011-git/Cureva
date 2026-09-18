"""Build a compact clinical briefing for the avatar's LLM turn.

Act 1 only; never imported by stage1/atlas.py.

Without this the avatar is a generic chatbot that says "I'm sorry to hear
that" to everything — it has no idea the person it is talking to is on a
study drug, already reported a rash last week, or is taking a medication the
protocol prohibits. That is both unconvincing in a demo and clinically
useless: the whole point of structured intake is that the interviewer knows
the chart.

What goes in is deliberately small. A full patient360 for one subject is
~112 records; pasting that into every turn would be slow, expensive, and
would bury the few facts that actually change what the avatar should say.
This selects: who they are, what arm they are on, their current medications,
their recent adverse events, any lab value currently outside its reference
range, and any finding already standing against them.
"""
from __future__ import annotations

from study import UnitMismatch, NoReferenceRange, central_range, standardise_lab

#: How many of each kind of record to include. Enough to be specific, small
#: enough to keep the turn inside a conversational latency budget.
MAX_CONMEDS = 8
MAX_AES = 5
MAX_ABNORMAL_LABS = 6


def _recent(records: list[dict], graph, cut, limit: int) -> list[dict]:
    """The most recent `limit` records, newest first, undated ones last."""
    dated = [(graph.record_date(r, cut), r) for r in records]
    dated.sort(key=lambda t: (t[0] is None, t[0] or 0), reverse=True)
    return [r for _, r in dated[:limit]]


def abnormal_labs(graph, usubjid: str, cut) -> list[str]:
    """Lab results currently outside their reference range, in central units.

    Goes through standardise_lab for the same reason every detector does: a
    local laboratory's value compared raw against the central range is either
    a missed abnormality or a false one.
    """
    out: list[tuple] = []
    for r in graph.records("LB", cut=cut, usubjid=usubjid):
        testcd = (r.get("LBTESTCD") or "").strip().upper()
        raw = graph.record_value(r, "LBORRES", cut)
        try:
            value, unit, converted = standardise_lab(testcd, raw, r.get("LBORRESU"), graph.ranges)
            _u, low, high = central_range(testcd, graph.ranges)
        except (UnitMismatch, NoReferenceRange):
            continue
        if value is None or high is None or low is None:
            continue
        if value > high or value < low:
            date = graph.record_date(r, cut)
            direction = "high" if value > high else "low"
            multiple = value / high if value > high else value / max(low, 1e-9)
            out.append((multiple, date, testcd, value, unit, direction,
                        r.get("VISIT"), low, high, converted, raw, r.get("LBORRESU")))
    # Most abnormal first — a 4x ULN transaminase matters more than a
    # marginally low glucose.
    out.sort(key=lambda t: t[0], reverse=True)

    lines = []
    for (_m, date, testcd, value, unit, direction, visit,
         low, high, converted, raw, raw_unit) in out[:MAX_ABNORMAL_LABS]:
        note = f" (reported {raw} {raw_unit}, converted)" if converted else ""
        lines.append(f"{testcd} {value:.4g} {unit} — {direction}, "
                     f"range {low:g}–{high:g} — at {visit or 'an unnamed visit'} "
                     f"on {date}{note}")
    return lines


def build(graph, usubjid: str, finding_graph=None, cut="unset") -> str:
    """A short plain-text briefing about one subject, for the system prompt.

    Returns "" when the subject is not in the study — the caller then runs
    without a briefing rather than asserting facts about someone who does not
    exist.
    """
    if cut == "unset":
        cut = graph.cut
    dm_rows = graph.records("DM", cut=cut, usubjid=usubjid)
    if not dm_rows:
        return ""
    dm = dm_rows[0]

    parts: list[str] = []
    parts.append(
        f"You are speaking with {usubjid}: {dm.get('AGE')}-year-old "
        f"{'woman' if (dm.get('SEX') or '').upper().startswith('F') else 'man'}, "
        f"site {graph.site_for(usubjid)}, {dm.get('COUNTRY')}, "
        f"randomised to the {dm.get('ARM')} arm. "
        f"Screening HbA1c {dm.get('SCR_HBA1C')}%. "
        f"First dose {graph.first_dose_date(usubjid, cut)}.")

    conmeds = graph.records("CM", cut=cut, usubjid=usubjid)
    if conmeds:
        named = []
        for r in _recent(conmeds, graph, cut, MAX_CONMEDS):
            trt = (graph.record_value(r, "CMTRT", cut) or "").strip()
            cls = (graph.record_value(r, "CMCLAS", cut) or "").strip()
            indication = (r.get("CMINDC") or "").strip()
            named.append(f"{trt} ({cls.lower().replace('_', ' ')})"
                         + (f" for {indication.lower()}" if indication else ""))
        parts.append("Current concomitant medications: " + "; ".join(named) + ".")
    else:
        parts.append("No concomitant medications on record.")

    aes = graph.records("AE", cut=cut, usubjid=usubjid)
    if aes:
        lines = []
        for r in _recent(aes, graph, cut, MAX_AES):
            term = (graph.record_value(r, "AETERM", cut) or "event").strip()
            sev = (graph.record_value(r, "AESEV", cut) or "").strip().lower()
            start = graph.record_date(r, cut)
            outcome = (r.get("AEOUT") or "").strip().lower()
            lines.append(f"{term} ({sev}, started {start}"
                         + (f", {outcome}" if outcome else "") + ")")
        parts.append("Adverse events already reported: " + "; ".join(lines) + ".")
    else:
        parts.append("No adverse events reported so far.")

    labs = abnormal_labs(graph, usubjid, cut)
    if labs:
        parts.append("Laboratory results outside the reference range: "
                     + "; ".join(labs) + ".")
    else:
        parts.append("No laboratory results outside the reference range.")

    if finding_graph is not None:
        theirs = [n for n in finding_graph.nodes.values() if n.usubjid == usubjid]
        if theirs:
            parts.append("Data-review findings already standing against this "
                         "subject: " + ", ".join(sorted({n.code for n in theirs}))
                         + ". Do not raise these with the patient as accusations; "
                         "they are context for what to ask about.")

    pro = graph.records(PRO := "PRO", cut=cut, usubjid=usubjid)
    if pro:
        said = "; ".join(f"{r.get('term')} (\"{r.get('raw_quote')}\")" for r in pro[-4:])
        parts.append(f"Already reported by the patient in earlier conversation: {said}.")

    return "\n".join(parts)
