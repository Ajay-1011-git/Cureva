"""T3.15 VERIFY — the forecast is context on a decision, never a report on its own.

PRD FR-18 is the whole point of this task: Act 4 must attach to a real
escalation passed to the human gate, and must never be published as a
freestanding prediction with no decision it is informing.

T3.0 established that `EscalationOut` has no field for a forecast — its only
free text is `summary` — so the forecast rides there, stated plainly. That is
the branch T3.15's own prompt anticipates, and this test asserts the schema
really has no better home rather than taking the audit's word for it.

Run: .venv/bin/python tests/test_t3_15_forecast_attached.py
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import EscalationOut, SurveillanceReport
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


state = Path(tempfile.mkdtemp(prefix="cureva-t315-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
report = watch.run_period(cuts=range(1, 13))

# ==========================================================================
print("=" * 74)
print("PART 1 — the organiser's schema really has nowhere else to put it")
print("=" * 74)
fields = set(EscalationOut.model_fields)
print(f"  EscalationOut fields : {sorted(fields)}")
print(f"  SurveillanceReport   : {sorted(SurveillanceReport.model_fields)}")
check("EscalationOut has no forecast/probability/risk field",
      not (fields & {"forecast", "probability", "risk", "prediction", "context"}))
check("  its only free-text field is `summary`",
      "summary" in fields and fields & {"summary", "reason"} == {"summary", "reason"})
check("SurveillanceReport has no forecast field either",
      "forecast" not in SurveillanceReport.model_fields)
print("  -> so the forecast is attached to EscalationOut.summary, explicitly "
      "labelled,\n     rather than by inventing a field the grader's type does "
      "not have.")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — real escalations carry their forecast")
print("=" * 74)
carrying = [e for e in report.escalations if "[Forecast context" in e.summary]
print(f"  escalations in the report            : {len(report.escalations)}")
print(f"  forecasts computed for a decision    : {len(watch.escalation_forecasts)}")
print(f"  escalations carrying forecast text   : {len(carrying)}")
check("at least one real escalation carries a forecast", len(carrying) > 0,
      f"{len(carrying)}")

example = next(e for e in carrying if e.site)
print(f"\n  ---- {example.id}  {example.code}  site={example.site} ----")
print(f"  decision: {example.decision}")
print(f"  summary:\n")
for line in example.summary.splitlines():
    print(f"      {line[:150]}")
check("  the forecast is clearly labelled as forecast context, not stated as fact",
      "[Forecast context" in example.summary)
check("  it states the no-action AND the intervention probability",
      "if nothing changes" in example.summary
      and "if the site is intervened on now" in example.summary)
check("  it carries its full assumptions inline (NFR-3)",
      "assumptions:" in example.summary
      and "Poisson process" in example.summary
      and "stated modelling assumption" in example.summary)
check("  it states the honest rollout count",
      "simulated rollouts" in example.summary)
check("  it carries NO invented date and NO external consequence",
      "carries no date and no external consequence" in example.summary)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — FR-18: no forecast exists without a decision to inform")
print("=" * 74)
escalated_sites = {r.site for r in crew.memory.escalations.values()}
all_sites = set(graph.sites())
print(f"  sites in the study                : {len(all_sites)}")
print(f"  distinct escalation sites         : {len(escalated_sites)} "
      f"(None = a study-level finding such as DOCUMENT_TAMPERED)")
check("every forecast belongs to an escalation that really exists",
      all(e in crew.memory.escalations for e in watch.escalation_forecasts))

# The real invariant: a forecast is ALWAYS about the site of the escalation it
# is attached to. A study-level escalation (site=None) correctly gets the
# study-wide forecast, which is the "study's" half of PRD FR-18's "each site's
# / study's" — not an orphan.
mismatched = [(e, f.site, crew.memory.escalations[e].site)
              for e, f in watch.escalation_forecasts.items()
              if f.site != crew.memory.escalations[e].site]
check("  every forecast is about the site of the escalation it informs",
      not mismatched, str(mismatched[:3]))

study_level = [e for e, r in crew.memory.escalations.items() if r.site is None
               and e in watch.escalation_forecasts]
print(f"  study-level escalations with the STUDY-WIDE forecast: {len(study_level)}")
if study_level:
    f = watch.escalation_forecasts[study_level[0]]
    print(f"      {crew.memory.escalations[study_level[0]].code}: {f.headline()[:110]}")
    check("    a study-level escalation gets the study-wide forecast, labelled "
          "'Study', not a site's", f.site is None
          and f.headline().startswith("Study"))

per_site = {f.site for f in watch.escalation_forecasts.values() if f.site}
check("  every per-site forecast names a site that really exists in the study",
      per_site <= all_sites, f"unknown: {sorted(per_site - all_sites)}")

view = watch.forecast_view()
print(f"\n  forecast_view() rows (what the API serves): {len(view)}")
check("every row served to the UI carries the decision it informed",
      all(row.get("escalation_id") and row.get("decision") for row in view))
check("  and every row's escalation is real",
      all(row["escalation_id"] in crew.memory.escalations for row in view))
check("  the view cannot serve a forecast with no decision",
      len(view) <= len(watch.escalation_forecasts))
if view:
    top = view[0]
    print(f"  highest-risk row: {top['site']} {top['code']} "
          f"decision={top['decision']} -> {top['headline'][:90]}")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — early cuts report 'no benchmark yet', not a false alarm")
print("=" * 74)
usable = [f for f in watch.escalation_forecasts.values() if not f.insufficient_history]
withheld = [f for f in watch.escalation_forecasts.values() if f.insufficient_history]
print(f"  usable forecasts        : {len(usable)}")
print(f"  honestly withheld       : {len(withheld)}")
if withheld:
    print(f"  a withheld one says:\n      {withheld[0].assumptions[0][:260]}")
check("some forecasts are honestly withheld early in the period",
      len(withheld) > 0, f"{len(withheld)}")
check("  a withheld forecast reports zero probability, not a near-certain alarm",
      all(f.breach_probability == 0.0 for f in withheld))
check("  and runs no rollouts it cannot justify",
      all(f.rollouts_run == 0 for f in withheld))
check("  and a withheld forecast is NOT attached to the escalation text",
      len(carrying) == len(usable), f"{len(carrying)} vs {len(usable)}")
check("no usable forecast rests on a degenerate threshold of zero",
      all(f.breach_threshold > 0 for f in usable))

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — the budget was respected and reported")
print("=" * 74)
budget = report.budget
print(f"  rollouts run this period : {budget['rollouts_run']:,}")
print(f"  time ledger              : {budget['time']['rollouts_available_now']} "
      f"available, {budget['time']['rollouts_run']:,} run")
# One forecast per (site, cut) is shared by every escalation it informs, so
# the reported figure must count DISTINCT simulation work. Summing per
# escalation would claim 62,500 rollouts for the 24,000 really run.
distinct = sum(f.rollouts_run for f in watch._forecast_cache.values() if f)
per_escalation = sum(f.rollouts_run for f in watch.escalation_forecasts.values())
print(f"  distinct forecasts computed  : {distinct:,} rollouts")
print(f"  summed per escalation        : {per_escalation:,} rollouts "
      f"(would overstate by {per_escalation - distinct:,})")
check("the reported figure counts DISTINCT simulation work, not one count per "
      "escalation sharing the same forecast",
      budget["rollouts_run"] == distinct, str(budget["rollouts_run"]))
check("  which is genuinely lower than the per-escalation sum",
      distinct < per_escalation, f"{distinct} vs {per_escalation}")
check("  and the walk stayed inside its wall-clock budget",
      not watch.time_budget.expired(),
      f"{watch.time_budget.elapsed_s():.1f}s of "
      f"{watch.time_budget.hard_deadline_s}s")
check("  one forecast per (site, cut), not one per escalation",
      len(watch._forecast_cache) < len(watch.escalation_forecasts),
      f"{len(watch._forecast_cache)} cached vs "
      f"{len(watch.escalation_forecasts)} escalations")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
