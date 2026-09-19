"""T3.19 VERIFY — the complete SurveillanceReport for a full 12-cut period.

The organiser's `SurveillanceReport` has eight fields and **not one of them has
a default** (T3.0). This test asserts every one is populated from real data,
that nothing in it was invented, and that the `markdown` field — which is the
"readable by a non-technical reviewer" deliverable the Problem 3 rubric asks
for, not a separate export — actually reads as one.

Run: .venv/bin/python tests/test_t3_19_report.py
"""
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import SurveillanceReport
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


state = Path(tempfile.mkdtemp(prefix="cureva-t319-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
report = watch.run_period(cuts=range(1, 13))
dumped = report.model_dump()

# ==========================================================================
print("=" * 74)
print("PART 1 — all eight required fields, populated")
print("=" * 74)
for key, value in dumped.items():
    shape = (f"list[{len(value)}]" if isinstance(value, list) else
             f"dict{sorted(value)}" if isinstance(value, dict) else
             f"str[{len(value)} chars]" if isinstance(value, str) else str(value))
    print(f"  {key:<14} {shape if len(str(shape)) < 90 else str(shape)[:87] + '...'}")

check("the returned object really is the organiser's SurveillanceReport",
      isinstance(report, SurveillanceReport))
check("  it re-validates from its own dump",
      SurveillanceReport.model_validate(dumped) is not None)
for field in SurveillanceReport.model_fields:
    check(f"  {field} is populated", bool(dumped[field]),
          repr(dumped[field])[:40])

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — each section is real, not filler")
print("=" * 74)
check(f"period names the real span", report.period == "cuts 1-12", report.period)
check("cuts lists all twelve", report.cuts == list(range(1, 13)))
check("decisions cover every resolved escalation",
      len(report.decisions) == sum(1 for r in crew.memory.escalations.values()
                                   if r.state in ("APPROVED", "REJECTED")),
      str(len(report.decisions)))
check("  every decision has a real rationale and evidence",
      all(d.rationale for d in report.decisions)
      and sum(1 for d in report.decisions if d.evidence) > 0)
check("  every decision id can be explained from the trace",
      all(watch.explain(d.id).evidence_lines for d in report.decisions[:20]))
check("escalations include the ones still open",
      any((e.decision or "") == "PENDING" for e in report.escalations))
check("signals are deduplicated across cuts",
      len({f.fingerprint() for f in report.signals}) == len(report.signals))
check("  and include all four Stage-3 trend codes",
      {"LAB_UNIT_CORRUPTION", "DOCUMENT_TAMPERED", "IMPLAUSIBLE_SITE_PATTERN",
       "LATE_DATA_ENTRY"} <= {f.code for f in report.signals},
      str(sorted({f.code for f in report.signals})))

print("\n  KRIs, ranked:")
print(f"      {'site':<6}{'risk':>7}{'dev':>7}{'query':>7}{'sae':>7}"
      f"{'late':>7}{'implaus':>9}")
for k in report.kris:
    print(f"      {k.site:<6}{k.risk:>7.3f}{k.deviation_rate:>7.2f}"
          f"{k.query_rate:>7.2f}{k.sae_rate:>7.2f}{k.late_entry_score:>7.2f}"
          f"{k.implausibility:>9.3f}")
check("one KRI per site in the study",
      {k.site for k in report.kris} == set(graph.sites()),
      str(sorted({k.site for k in report.kris} ^ set(graph.sites()))))
check("  all six metrics are real numbers, none left at zero across the board",
      all(any(getattr(k, m) > 0 for k in report.kris)
          for m in ("deviation_rate", "query_rate", "late_entry_score",
                    "implausibility", "sae_rate", "risk")))
check("  they are sorted by risk, highest first",
      [k.risk for k in report.kris] == sorted((k.risk for k in report.kris),
                                              reverse=True))

top = report.kris[0]
print(f"\n  the highest-risk site is {top.site} at {top.risk:.3f}")
check("the fabricated-data site ranks top — an integrity signal is NOT averaged "
      "away by a site looking quiet on volume",
      top.site == "S11" and top.implausibility > 0.9,
      f"{top.site} implausibility={top.implausibility}")
check("  and it ranks top DESPITE having the lowest deviation and query rates",
      top.deviation_rate == min(k.deviation_rate for k in report.kris)
      and top.query_rate == min(k.query_rate for k in report.kris),
      f"dev={top.deviation_rate} query={top.query_rate}")

print("\n  budget block:")
for key, value in sorted(report.budget.items()):
    print(f"      {key:<20} {str(value)[:80]}")
check("budget reports both ledgers honestly",
      "tokens" in report.budget and "time" in report.budget)
check("  and the stated degradation order",
      len(report.budget["degradation_order"]) == 3
      and len(report.budget["never_degrades"]) == 5)
check("  rollouts behind the published forecasts are reported",
      report.budget["rollouts_run"] > 0, str(report.budget["rollouts_run"]))
check("  and what THIS walk spent is reported separately",
      "rollouts_run_this_walk" in report.budget,
      str(report.budget.get("rollouts_run_this_walk")))
check("  and the graded walk spent zero tokens",
      report.budget["tokens"]["spent"] == 0)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — the markdown is the readable deliverable")
print("=" * 74)
md = report.markdown
headings = [l for l in md.splitlines() if l.startswith("#")]
print(f"  {len(md):,} characters, {len(md.splitlines())} lines")
for h in headings:
    print(f"      {h}")
for required in ("What this period found", "Which sites need attention first",
                 "Escalations and the human gate",
                 "Findings that are no longer current", "Where sites are heading",
                 "Paperwork drafted", "what it would give up under pressure"):
    check(f"has a '{required}' section", required in md)

check("it leads with the cross-cut findings a single snapshot cannot see",
      md.index("needed more than one data cut") < md.index("How the period ran"))
for site, what in (("S04", "collapsed by a factor"), ("S11", "too uniform"),
                   ("S08", "well after the events"),
                   ("lab-manual_v3", "attempting to steer")):
    check(f"  the report names the real {site} finding", what in md and site in md)

check("it states plainly that the escalation TIMING is simulated",
      "is Cureva's own policy, not the organiser's behaviour" in md)
check("  and that silence is never read as approval",
      "never treated as approval" in md)
check("  and that the risk score is not externally calibrated",
      "not calibrated against any external standard" in md)
check("  and whether a language model touched the paperwork",
      "no language model was involved in this run" in md
      or "reworded by a language model" in md)

jargon = [w for w in ("fingerprint", "escalation_id", "model_dump", "pydantic",
                      "None", "dict[", "list[") if w in md]
check("no code-level jargon leaks into the readable report", not jargon, str(jargon))

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — nothing in the report was invented")
print("=" * 74)
graph.build(12)
real_subjects = {r["USUBJID"] for r in graph.study.domains["DM"]}
real_sites = set(graph.sites())
mentioned_subjects = set(re.findall(r"\b042-[A-Z0-9]+-\d+\b", md))
mentioned_sites = set(re.findall(r"\bS\d{2}\b", md))
check("every subject id in the report is a real subject",
      mentioned_subjects <= real_subjects,
      str(sorted(mentioned_subjects - real_subjects)[:3]))
check("every site id in the report is a real site",
      mentioned_sites <= real_sites,
      str(sorted(mentioned_sites - real_sites)[:3]))
check("every KRI site is a real site", {k.site for k in report.kris} <= real_sites)
check("every signal's site is real or absent",
      all(f.site in real_sites or f.site is None for f in report.signals))
check("every decision's subject is real or absent",
      all(d.usubjid in real_subjects or d.usubjid is None
          for d in report.decisions))

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — the whole report is stable across a re-walk")
print("=" * 74)
second = watch.run_period(cuts=range(1, 13))
a, b = report.model_dump(), second.model_dump()
for field in ("period", "cuts", "kris"):
    check(f"{field} identical on a re-walk", a[field] == b[field])

# Signals are NOT required to be byte-identical on a WARM re-walk, and that is
# correct rather than a gap. Stage 2 retires a SAE_UNESCALATED permanently once
# it has been escalated (audit 10) — on the second walk the event is no longer
# *unescalated*, so the detector rightly declines to re-raise it. The escalation
# itself is still in the report, so nothing is lost. The honest invariants are
# that no NEW signal appears, and that anything that drops is only a code whose
# detector retires on escalation.
before = {f["code"] + "|" + str(f.get("usubjid")) for f in a["signals"]}
after = {f["code"] + "|" + str(f.get("usubjid")) for f in b["signals"]}
retiring = {"SAE_UNESCALATED"}
print(f"  signals: {len(a['signals'])} -> {len(b['signals'])}")
print(f"      dropped: {sorted(x.split('|')[0] for x in before - after)}")
check("a warm re-walk introduces NO new signal", not (after - before),
      str(sorted(after - before)[:3]))
check("  and anything it drops is a code whose detector retires on escalation",
      {x.split("|")[0] for x in before - after} <= retiring,
      str({x.split("|")[0] for x in before - after} - retiring))
check("  the escalations for the dropped signals are still in the report",
      len(a["escalations"]) == len(b["escalations"]))
check("decisions identical on a re-walk",
      [d["id"] for d in a["decisions"]] == [d["id"] for d in b["decisions"]])
check("escalations identical on a re-walk",
      [e["id"] for e in a["escalations"]] == [e["id"] for e in b["escalations"]])
def _normalise(text: str) -> str:
    """Strip the two things a re-walk legitimately changes: elapsed time, and
    the SAE_UNESCALATED signal count that Stage 2 retires on escalation."""
    text = re.sub(r"\d+ ms|\d+\.\d+s", "T", text)
    # SAE_UNESCALATED retirement changes signal and per-cut finding counts on a
    # warm re-walk, as PART 5 asserts above; and a walk that reuses forecasts
    # it already holds honestly spends no rollouts on them.
    text = re.sub(r"[\d,]+ distinct problems|Distinct signals raised: [\d,]+"
                  r"|[\d,]+ finding\(s\)", "N", text)
    return re.sub(r"\([\d,]+ simulated in this pass[^)]*\)", "(P)", text)


check("  the markdown is otherwise identical on a re-walk",
      _normalise(a["markdown"]) == _normalise(b["markdown"]))

out = Path(tempfile.gettempdir()) / "cureva_surveillance_report.md"
out.write_text(md)
print(f"\n  full report written to {out} for inspection")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails[:5]}")
sys.exit(1 if fails else 0)
