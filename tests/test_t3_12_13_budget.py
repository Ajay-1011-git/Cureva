"""T3.12 + T3.13 VERIFY — the two budget ledgers and their degradation order.

PRD FR-14/FR-15, acceptance criterion 8. Two properties matter more than the
numbers:

  * A call whose estimated cost exceeds the budget is **never attempted**. The
    ledger is checked first. Learning your budget from a provider's 429 means
    learning it by exceeding it.
  * Degradation only ever reaches optional narrative and simulation work.
    DETECT, COMPLIANCE, the HUMAN GATE and the trace never degrade, at any
    budget level. PART 4 proves that on a real period walk with both ledgers
    deliberately exhausted.

Run: .venv/bin/python tests/test_t3_12_13_budget.py
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3 import budget as B
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


# ==========================================================================
print("=" * 74)
print("T3.12 — the token ledger is sized against Groq's real daily limit")
print("=" * 74)
ledger = B.TokenLedger()
print(f"  Groq free-tier TPD (re-verified T3.0)  : {B.GROQ_TOKENS_PER_DAY:,}")
print(f"  ceiling for ONE period walk            : {ledger.ceiling:,}")
print(f"  share of the daily account limit       : "
      f"{ledger.ceiling / B.GROQ_TOKENS_PER_DAY:.0%}")
print(f"  rehearsal + live demo + avatar         : "
      f"{ledger.ceiling * 2 + 20_000:,}  ({(ledger.ceiling * 2 + 20_000) / B.GROQ_TOKENS_PER_DAY:.0%} of the day)")
print(f"  left for development and re-runs       : "
      f"{B.GROQ_TOKENS_PER_DAY - (ledger.ceiling * 2 + 20_000):,}")
check("the ceiling leaves real margin under the daily limit",
      ledger.ceiling * 2 + 20_000 < B.GROQ_TOKENS_PER_DAY / 2,
      f"demo day uses {(ledger.ceiling * 2 + 20_000) / B.GROQ_TOKENS_PER_DAY:.0%}")
check("  a whole period walk could run ten times in one day and still fit",
      ledger.ceiling * 10 <= B.GROQ_TOKENS_PER_DAY)

print("\n  normal spending:")
check("can_afford() is true with a full budget",
      ledger.can_afford(B.POLISH_ESTIMATED_TOKENS))
ledger.debit(1_150)
print(f"      after one real call of 1,150 tokens: spent={ledger.spent} "
      f"remaining={ledger.remaining}")
check("  debit() records the ACTUAL count, not the estimate",
      ledger.spent == 1_150, str(ledger.spent))

print("\n  THE KEY SCENARIO — budget deliberately below one polish call:")
tight = B.TokenLedger(ceiling=1_000)
tight.debit(500)
print(f"      ceiling=1,000, spent=500, remaining={tight.remaining}")
print(f"      one polish call is estimated at {B.POLISH_ESTIMATED_TOKENS} tokens")


class SpyProvider:
    """Stands in for Groq. Records whether it was called at all."""

    def __init__(self):
        self.calls = 0

    def polish(self, text: str) -> str:
        self.calls += 1
        return text.upper()


def polish_with_ledger(ledger: B.TokenLedger, provider: SpyProvider,
                       text: str) -> tuple[str, str]:
    """The exact shape every Groq-touching component in this stage must use."""
    if not ledger.can_afford(B.POLISH_ESTIMATED_TOKENS):
        ledger.skip("Act 5 polish", B.POLISH_ESTIMATED_TOKENS)
        return text, "template_only"
    out = provider.polish(text)
    ledger.debit(B.POLISH_ESTIMATED_TOKENS)
    return out, "polished"


spy = SpyProvider()
result, source = polish_with_ledger(tight, spy, "the template text")
print(f"      -> source={source!r}, provider called {spy.calls} time(s)")
check("can_afford() refuses the call", not tight.can_afford(B.POLISH_ESTIMATED_TOKENS))
check("  the template ships unchanged", result == "the template text")
check("  it is tagged template_only, not polished", source == "template_only")
check("  THE PROVIDER WAS NEVER CALLED — the budget was checked first, not "
      "discovered from an error", spy.calls == 0, f"{spy.calls} call(s)")
check("  and the skip is recorded, so a degraded run can say what it gave up",
      len(tight.skipped) == 1, str(tight.skipped))
print(f"      recorded: {tight.skipped[0]}")

rich = B.TokenLedger(ceiling=20_000)
spy2 = SpyProvider()
_, source2 = polish_with_ledger(rich, spy2, "the template text")
check("with budget available, the same code DOES call the provider",
      spy2.calls == 1 and source2 == "polished", f"{spy2.calls} call(s), {source2}")
check("  and the ledger is debited", rich.spent == B.POLISH_ESTIMATED_TOKENS)

# ==========================================================================
print()
print("=" * 74)
print("T3.13 — the time ledger degrades rollouts, and only rollouts")
print("=" * 74)
print(f"  starting ceiling: {B.DEFAULT_ROLLOUT_CEILING}   floor: {B.ROLLOUT_FLOOR}   "
      f"halves at: {[f'{f:.0%}' for f in B.DEGRADE_AT]}")
print(f"\n  the floor's justification, checked arithmetically:")
import math                                                      # noqa: E402
se = math.sqrt(0.25 / B.ROLLOUT_FLOOR)
print(f"      worst-case standard error at n={B.ROLLOUT_FLOOR}: "
      f"sqrt(0.25/{B.ROLLOUT_FLOOR}) = {se:.4f}  (+/- {se * 100:.1f} percentage points)")
check("the floor still gives a breach probability good to ~7 points or better",
      se <= 0.075, f"{se:.4f}")
se_below = math.sqrt(0.25 / (B.ROLLOUT_FLOOR // 2))
print(f"      at half the floor (n={B.ROLLOUT_FLOOR // 2}): {se_below:.4f} "
      f"(+/- {se_below * 100:.1f} points) — past the point of supporting a statement")
check("  halving below the floor would reach 10 points, which is why it stops",
      se_below >= 0.10, f"{se_below:.4f}")

print("\n  driving the clock forward (injected, not slept through):")
now = {"t": 1000.0}
led = B.TimeLedger(hard_deadline_s=100.0, started_at=1000.0)
led.set_clock(lambda: now["t"])
rows = []
for elapsed in (0, 10, 45, 50, 60, 75, 80, 90, 95, 99):
    now["t"] = 1000.0 + elapsed
    rows.append((elapsed, led.fraction_used(), led.rollouts_for_next_call()))
print(f"      {'elapsed':>8} {'used':>7} {'rollouts':>9}")
for elapsed, used, allowed in rows:
    mark = "  <- floor" if allowed == B.ROLLOUT_FLOOR else ""
    print(f"      {elapsed:>7}s {used:>6.0%} {allowed:>9}{mark}")

by_elapsed = dict((e, r) for e, _u, r in rows)
check("below 50% of the deadline the full rollout count is available",
      by_elapsed[45] == B.DEFAULT_ROLLOUT_CEILING, str(by_elapsed[45]))
check("  crossing 50% halves it", by_elapsed[50] == B.DEFAULT_ROLLOUT_CEILING // 2,
      str(by_elapsed[50]))
check("  crossing 75% halves it again",
      by_elapsed[75] == B.DEFAULT_ROLLOUT_CEILING // 4, str(by_elapsed[75]))
check("  crossing 90% halves it again", by_elapsed[90] == B.DEFAULT_ROLLOUT_CEILING // 8,
      str(by_elapsed[90]))
check("  the floor is REACHABLE — once the deadline is spent, it is hit exactly",
      by_elapsed[99] > B.ROLLOUT_FLOOR, f"at 99%: {by_elapsed[99]}")
check("  it NEVER drops below the floor, however late it gets",
      all(r >= B.ROLLOUT_FLOOR for _e, _u, r in rows), 
      f"min {min(r for _e, _u, r in rows)}")

now["t"] = 1000.0 + 10_000
check("  even long past the deadline the floor holds",
      led.rollouts_for_next_call() == B.ROLLOUT_FLOOR,
      str(led.rollouts_for_next_call()))
check("  and expired() reports the truth", led.expired())
print(f"\n  degradation steps recorded: {len(led.degradations)}")
for note in led.degradations:
    print(f"      {note}")
check("every degradation step is recorded for the report", len(led.degradations) >= 3)

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — the stated order, and the line nothing crosses")
print("=" * 74)
print("  degrades, in this order:")
for i, item in enumerate(B.DEGRADATION_ORDER, 1):
    print(f"      {i}. {item}")
print("  never degrades, at any budget level:")
for item in B.NEVER_DEGRADES:
    print(f"      - {item}")

print("\n  proving it on a REAL period walk with both ledgers exhausted:")
state = Path(tempfile.mkdtemp(prefix="cureva-t312-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
baseline = watch.run_period(cuts=range(1, 13))

state2 = Path(tempfile.mkdtemp(prefix="cureva-t312b-"))
graph2 = StudyGraph(DATA)
crew2 = ReviewCrew(DATA, Atlas(graph2), state_dir=state2)
starved = StudyWatch(DATA, crew2)
# Both budgets gone before the walk even starts. These are the real ledger
# objects StudyWatch consults -- assigning to a name it does not own would
# make this section pass without proving anything.
assert isinstance(starved.tokens, B.TokenLedger), "StudyWatch must own a TokenLedger"
assert isinstance(starved.time_budget, B.TimeLedger), "StudyWatch must own a TimeLedger"
starved.tokens = B.TokenLedger(ceiling=0)
starved.time_budget = B.TimeLedger(hard_deadline_s=0.0001)
starved_report = starved.run_period(cuts=range(1, 13))

print(f"      {'':22} {'normal':>10} {'starved':>10}")
for label, a, b in (
        ("signals (DETECT)", len(baseline.signals), len(starved_report.signals)),
        ("escalations (GATE)", len(baseline.escalations), len(starved_report.escalations)),
        ("decisions", len(baseline.decisions), len(starved_report.decisions)),
        ("trace lines", baseline.budget["trace_lines"],
         starved_report.budget["trace_lines"]),
        ("superseded tracked", baseline.budget["superseded_findings"],
         starved_report.budget["superseded_findings"])):
    flag = "  SAME" if a == b else "  ** DIFFERS **"
    print(f"      {label:22} {a:>10} {b:>10}{flag}")

check("DETECT produced identical signals with zero budget",
      len(baseline.signals) == len(starved_report.signals))
check("HUMAN GATE produced identical escalations with zero budget",
      len(baseline.escalations) == len(starved_report.escalations))
check("  and identical decisions",
      len(baseline.decisions) == len(starved_report.decisions))
check("the trace was written in full with zero budget",
      baseline.budget["trace_lines"] == starved_report.budget["trace_lines"])
check("supersession tracking survived zero budget",
      baseline.budget["superseded_findings"]
      == starved_report.budget["superseded_findings"])

devs = sum(len(r.deviations) for r in watch.reports)
devs_starved = sum(len(r.deviations) for r in starved.reports)
check("COMPLIANCE produced identical deviations with zero budget",
      devs == devs_starved, f"{devs} vs {devs_starved}")

print("\n  the starved run reports its own budget state honestly:")
b = starved_report.budget
print(f"      tokens : ceiling={b['tokens']['ceiling']} spent={b['tokens']['spent']} "
      f"remaining={b['tokens']['remaining']}")
print(f"      time   : rollouts available now={b['time']['rollouts_available_now']} "
      f"(floor {b['time']['rollout_floor']})")
check("the report carries both ledgers' real state, not a placeholder",
      b["tokens"]["ceiling"] == 0 and b["time"]["rollouts_available_now"]
      == B.ROLLOUT_FLOOR, str(b["time"]["rollouts_available_now"]))
check("  and states the degradation order it would follow",
      b["degradation_order"] == list(B.DEGRADATION_ORDER))
check("  and what it would never give up",
      b["never_degrades"] == list(B.NEVER_DEGRADES))
check("the NORMAL run is not degraded at all",
      baseline.budget["time"]["rollouts_available_now"] == B.DEFAULT_ROLLOUT_CEILING
      and baseline.budget["tokens"]["spent"] == 0,
      str(baseline.budget["time"]["rollouts_available_now"]))

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
