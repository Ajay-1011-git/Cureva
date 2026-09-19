"""T3.14 VERIFY — Act 4's Monte Carlo forecast on real per-site deviation counts.

Run against the real practice study through cut 9, forecasting to cut 12.

The properties that matter more than the numbers:

  * **Assumptions are never empty and never omitted** (NFR-3). A probability
    without its assumptions is a number pretending to be a fact.
  * **The breach threshold is the study's own observed spread**, so a reviewer
    can check it against the data in front of them and a hidden study of a
    different size needs no adjustment.
  * **Insufficient history returns zero and says so**, never a small invented
    number.
  * **It is deterministic.** An irreproducible number attached to a decision is
    not evidence.

Run: .venv/bin/python tests/test_t3_14_forecast.py
"""
import logging
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forecast import montecarlo as MC
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.budget import TimeLedger
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
AS_OF, LAST = 9, 12
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


# ---- real arrival counts from a real walk through cut 9 --------------------
state = Path(tempfile.mkdtemp(prefix="cureva-t314-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
watch.run_period(cuts=range(1, AS_OF + 1))

seen: set[str] = set()
arrivals: dict[str, dict[int, int]] = defaultdict(dict)
for report in watch.reports:
    for deviation in report.deviations:
        fp = deviation.fingerprint()
        if fp in seen:
            continue
        seen.add(fp)
        site = deviation.site or "?"
        arrivals[site][report.cut] = arrivals[site].get(report.cut, 0) + 1
arrivals = dict(arrivals)

print("=" * 74)
print(f"REAL new-deviation arrivals per cut, through cut {AS_OF}")
print("=" * 74)
print("  site " + "".join(f"{c:>4}" for c in range(1, AS_OF + 1)) + "   total")
for site in sorted(arrivals):
    row = [arrivals[site].get(c, 0) for c in range(1, AS_OF + 1)]
    print(f"  {site}  " + "".join(f"{v:>4}" for v in row) + f"   {sum(row)}")
check(f"{len(seen)} distinct deviations were observed across 12 real sites",
      len(seen) > 100 and len(arrivals) >= 12, f"{len(seen)} / {len(arrivals)} sites")

# ==========================================================================
print()
print("=" * 74)
print(f"PART 1 — real ForecastResults, cut {AS_OF} -> {LAST}")
print("=" * 74)
busiest = max(arrivals, key=lambda s: sum(arrivals[s].values()))
quietest = min(arrivals, key=lambda s: sum(arrivals[s].values()))
results = {}
for site in (busiest, quietest):
    f = MC.forecast_site(site, arrivals, cut=AS_OF, last_cut=LAST, rollouts=500)
    results[site] = f
    print(f"\n  ---- {site} "
          f"({'busiest' if site == busiest else 'quietest'} site, "
          f"{sum(arrivals[site].values())} deviations so far) ----")
    print(f"  {f.headline()}")
    print(f"    site                              : {f.site}")
    print(f"    rate_per_cut                      : {f.rate_per_cut}")
    print(f"    breach_threshold                  : {f.breach_threshold}")
    print(f"    horizon_cuts                      : {f.horizon_cuts}")
    print(f"    breach_probability                : {f.breach_probability}")
    print(f"    breach_probability_w_intervention : {f.breach_probability_with_intervention}")
    print(f"    median_breach_cut                 : {f.median_breach_cut}")
    print(f"    rollouts_run                      : {f.rollouts_run}")
    print(f"    assumptions ({len(f.assumptions)}):")
    for a in f.assumptions:
        print(f"      - {a}")

study = MC.forecast_study(arrivals, cut=AS_OF, last_cut=LAST, rollouts=500)
print(f"\n  ---- study-wide ----")
print(f"  {study.headline()}")
print(f"    rate={study.rate_per_cut} threshold={study.breach_threshold} "
      f"p={study.breach_probability}")

for site, f in results.items():
    check(f"{site}: assumptions are present and non-empty",
          len(f.assumptions) >= 5, f"{len(f.assumptions)}")
    check(f"  {site}: probability is a real fraction",
          0.0 <= f.breach_probability <= 1.0, str(f.breach_probability))
    check(f"  {site}: rollouts_run is the honest count actually simulated",
          f.rollouts_run == 500, str(f.rollouts_run))
    check(f"  {site}: intervention is never WORSE than doing nothing",
          f.breach_probability_with_intervention <= f.breach_probability,
          f"{f.breach_probability_with_intervention} vs {f.breach_probability}")
    check(f"  {site}: the assumptions state the estimation window and its counts",
          "estimated from the last" in " ".join(f.assumptions)
          and "counts [" in " ".join(f.assumptions))
    check(f"  {site}: the assumptions state the intervention effect as an assumption",
          "stated modelling assumption, not a measured effect" in " ".join(f.assumptions))
    check(f"  {site}: the assumptions carry no date and no external consequence",
          "carries no date and no external consequence" in " ".join(f.assumptions))

check("the busiest site is judged more likely to breach than the quietest",
      results[busiest].breach_probability >= results[quietest].breach_probability,
      f"{busiest}={results[busiest].breach_probability} "
      f"{quietest}={results[quietest].breach_probability}")
check("a breached rollout reports a median breach cut inside the horizon",
      results[busiest].median_breach_cut is None
      or AS_OF < results[busiest].median_breach_cut <= LAST,
      str(results[busiest].median_breach_cut))

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the breach threshold is RELATIVE to the study's own spread")
print("=" * 74)
threshold, benchmark = MC.breach_threshold(arrivals, busiest, AS_OF, 3)
print(f"  for {busiest}, the benchmark site is {benchmark} at {threshold} "
      f"deviations in 3 consecutive cuts")
check("the benchmark is another real site, never the site being forecast",
      benchmark != busiest, benchmark)
check("  and it is a real observed number from this study",
      threshold == MC._worst_stretch(arrivals[benchmark], AS_OF, 3),
      f"{threshold}")

doubled = {s: {c: n * 2 for c, n in a.items()} for s, a in arrivals.items()}
t_doubled, _ = MC.breach_threshold(doubled, busiest, AS_OF, 3)
print(f"  in a study with twice the deviations, the threshold becomes {t_doubled}")
check("the threshold scales with the study rather than staying fixed",
      t_doubled == threshold * 2, f"{threshold} -> {t_doubled}")
check("  so a hidden study of a different size needs no adjustment",
      t_doubled != threshold)

print("\n  the study-wide forecast uses its OWN worst stretch, not a site's:")
print(f"      study threshold={study.breach_threshold}  "
      f"(a single site's is {threshold})")
check("the study-wide benchmark is far larger than one site's",
      study.breach_threshold > threshold * 2,
      f"{study.breach_threshold} vs {threshold}")
check("  and its probability is not 100% by construction",
      study.breach_probability < 1.0, str(study.breach_probability))

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — a quiet cut is a zero, not a missing value (regression)")
print("=" * 74)
sparse = {"SPARSE": {6: 2}, "OTHER": {6: 3, 7: 3, 8: 3, 9: 3}}
rate, cuts, counts = MC.estimate_rate(sparse["SPARSE"], 9, first_cut=6)
print(f"  a site with arrivals {sparse['SPARSE']} at cut 9:")
print(f"      window cuts {cuts}, counts {counts}, rate {rate}")
check("the three quiet cuts are counted as zeros", counts == [2, 0, 0, 0], str(counts))
check("  giving a rate of 0.5, not 2.0",
      abs(rate - 0.5) < 1e-9, str(rate))
print("  (building the window from the dict's own keys would have given 2.0 — "
      "a fourfold\n   overestimate, and it is a real site in this study that "
      "exposed it)")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — honesty at the edges: no fabricated numbers")
print("=" * 74)
empty = MC.forecast_site("NOBODY", {"NOBODY": {}, "OTHER": {1: 5}}, cut=9,
                         last_cut=12, rollouts=500)
print(f"  a site with NO deviations at all:")
print(f"      p={empty.breach_probability} insufficient_history="
      f"{empty.insufficient_history} rollouts_run={empty.rollouts_run}")
print(f"      final assumption: {empty.assumptions[-1]}")
check("no history -> probability is exactly zero, not a small invented number",
      empty.breach_probability == 0.0)
check("  and it is flagged as insufficient history", empty.insufficient_history)
check("  and it says so in its own assumptions",
      "no rate to project" in " ".join(empty.assumptions))
check("  and reports zero rollouts, because none were run",
      empty.rollouts_run == 0, str(empty.rollouts_run))
check("  its headline says so in plain words",
      "not enough history" in empty.headline(), empty.headline())

ended = MC.forecast_site(busiest, arrivals, cut=12, last_cut=12, rollouts=500)
check("a zero-length horizon returns honestly rather than dividing by zero",
      ended.horizon_cuts == 0 and ended.breach_probability == 0.0
      and bool(ended.assumptions))

try:
    MC.forecast_site("X", {}, cut=9, last_cut=12, rollouts=10)
    no_crash = True
except Exception as exc:                                          # noqa: BLE001
    no_crash = False
    print(f"      raised: {exc}")
check("an entirely empty study does not raise", no_crash)

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — determinism and budget integration")
print("=" * 74)
a = MC.forecast_site(busiest, arrivals, cut=AS_OF, last_cut=LAST, rollouts=500)
b = MC.forecast_site(busiest, arrivals, cut=AS_OF, last_cut=LAST, rollouts=500)
check("two calls give byte-identical results",
      a.model_dump() == b.model_dump(), f"{a.breach_probability} vs {b.breach_probability}")

ledger = TimeLedger(hard_deadline_s=100.0, started_at=1000.0)
clock = {"t": 1000.0}
ledger.set_clock(lambda: clock["t"])
print("  rollout count taken from the time ledger as it degrades:")
for elapsed in (0, 50, 75, 95):
    clock["t"] = 1000.0 + elapsed
    n = ledger.rollouts_for_next_call()
    f = MC.forecast_site(busiest, arrivals, cut=AS_OF, last_cut=LAST, rollouts=n)
    print(f"      {elapsed:>3}s elapsed -> {n:>4} rollouts -> "
          f"p={f.breach_probability:.3f}  (rollouts_run={f.rollouts_run})")
    check(f"  at {elapsed}s the forecast honestly reports {n} rollouts run",
          f.rollouts_run == n, str(f.rollouts_run))

clock["t"] = 1000.0
full = MC.forecast_site(busiest, arrivals, cut=AS_OF, last_cut=LAST,
                        rollouts=ledger.rollouts_for_next_call())
clock["t"] = 1000.0 + 200
floored = MC.forecast_site(busiest, arrivals, cut=AS_OF, last_cut=LAST,
                           rollouts=ledger.rollouts_for_next_call())
print(f"\n  full budget: p={full.breach_probability} ({full.rollouts_run} rollouts)")
print(f"  at the floor: p={floored.breach_probability} ({floored.rollouts_run} rollouts)")
check("degrading rollouts still produces a usable estimate, not a broken one",
      abs(full.breach_probability - floored.breach_probability) < 0.15,
      f"{full.breach_probability} vs {floored.breach_probability}")
check("  and the degraded run says how few rollouts it used",
      floored.rollouts_run == ledger.floor, str(floored.rollouts_run))

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
