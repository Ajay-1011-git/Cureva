"""Period idempotency — FR-12 / NFR-5 / acceptance criterion 2.

"Re-running the same period (or the same cut within it) shall raise zero new
queries and zero new escalations beyond what the first run already raised."

This test exists because that requirement was genuinely broken, and the bug was
invisible until a full period was walked twice.

**The bug.** MEDICAL REVIEW escalates a monitor-only finding when the subject
already carries COMPOUNDING_AT or more flagged findings. Stage 2 stores those
flags as a MAXIMUM rather than a sum, which makes re-running one CUT idempotent
and was verified as such. But a period walk replays cut 1 *after* cut 12 has
been seen — so on the second walk, cut 1 read the end-of-period flag counts
instead of its own. Measured on the practice study: subjects genuinely flagged
once at cut 1 carried counts of 3 and 4, crossed the threshold, flipped
MISSING_EXPOSURE_RECORD from monitor-only to escalation-worthy, and raised
8 escalations the first walk never raised.

**The fix.** `run_period()` clears the derived flag counts before walking,
because a period walk replays the study from its first cut and those counts are
re-derived by the walk itself. Nothing else is cleared.

Run: .venv/bin/python tests/test_t3_18_idempotency.py
"""
import hashlib
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from stage2.crew import COMPOUNDING_AT, ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def fingerprint(watch: StudyWatch, report) -> dict:
    """Everything that must be identical between two walks of one period."""
    memory = watch.crew.memory
    return {
        "escalations": len(memory.escalations),
        "escalation_ids": hashlib.sha1(
            json.dumps(sorted(memory.escalations)).encode()).hexdigest()[:16],
        "states": dict(Counter("send_failed" if r.send_failed else r.state
                               for r in memory.escalations.values())),
        "queries": len(memory.queries_raised),
        "query_keys": hashlib.sha1(
            json.dumps(sorted(memory.queries_raised)).encode()).hexdigest()[:16],
        "signals": len(report.signals),
        "decisions": len(report.decisions),
        "artifacts": len(watch.artifacts),
        "superseded": len(watch.memory.superseded),
        "asked_at": hashlib.sha1(
            json.dumps(sorted(watch.memory.asked_at.items())).encode()).hexdigest()[:16],
        "pending_queue": hashlib.sha1(
            json.dumps(sorted(watch.memory.pending_queue.items())).encode()).hexdigest()[:16],
    }


# ==========================================================================
print("=" * 74)
print("PART 1 — three consecutive walks of the same period, warm memory")
print("=" * 74)
state = Path(tempfile.mkdtemp(prefix="cureva-t318-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)

snapshots = []
for n in (1, 2, 3):
    report = watch.run_period(cuts=range(1, 13))
    snapshots.append(fingerprint(watch, report))
    print(f"  walk {n}: escalations={snapshots[-1]['escalations']} "
          f"queries={snapshots[-1]['queries']} signals={snapshots[-1]['signals']} "
          f"artifacts={snapshots[-1]['artifacts']} "
          f"states={snapshots[-1]['states']}")

first = snapshots[0]
check("walk 2 raises ZERO new escalations",
      snapshots[1]["escalations"] == first["escalations"],
      f"{first['escalations']} -> {snapshots[1]['escalations']}")
check("walk 3 raises ZERO new escalations",
      snapshots[2]["escalations"] == first["escalations"],
      f"{first['escalations']} -> {snapshots[2]['escalations']}")
check("walk 2 raises ZERO new queries",
      snapshots[1]["queries"] == first["queries"],
      f"{first['queries']} -> {snapshots[1]['queries']}")
check("walk 3 raises ZERO new queries",
      snapshots[2]["queries"] == first["queries"])
for key in ("escalation_ids", "query_keys", "states", "decisions", "artifacts",
            "superseded", "asked_at", "pending_queue"):
    check(f"  {key} identical across all three walks",
          snapshots[0][key] == snapshots[1][key] == snapshots[2][key],
          f"{snapshots[0][key]} / {snapshots[1][key]} / {snapshots[2][key]}")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the specific bug this guards: compounded flags at cut 1")
print("=" * 74)
print(f"  COMPOUNDING_AT = {COMPOUNDING_AT}")
cold_state = Path(tempfile.mkdtemp(prefix="cureva-t318-cold-"))
cold_crew = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=cold_state)
cold_crew.run_cycle(1, 1)
cold_flags = dict(cold_crew.memory.subject_flags)
warm_flags = dict(crew.memory.subject_flags)
inflated = {s: (cold_flags[s], warm_flags.get(s, 0)) for s in cold_flags
            if warm_flags.get(s, 0) > cold_flags[s]}
print(f"  subjects flagged at a cold cut 1        : {len(cold_flags)}")
print(f"  of those, carrying a HIGHER count after a full walk: {len(inflated)}")
example = sorted(inflated.items())[:3]
for subject, (cold, warm) in example:
    print(f"      {subject}: cut-1 count {cold} -> end-of-period {warm}")
check("the period genuinely does inflate flag counts — the hazard is real",
      len(inflated) > 0, f"{len(inflated)} subjects")
check("  and some cross the compounding threshold",
      any(c < COMPOUNDING_AT <= w for c, w in inflated.values()))

crossing = [s for s, (c, w) in inflated.items() if c < COMPOUNDING_AT <= w]
print(f"  subjects whose count crosses the threshold over the period: {len(crossing)}")
print("  -> if run_period() did not re-derive these, walk 2's cut 1 would judge")
print("     them by end-of-period counts and escalate findings walk 1 did not.")
check("run_period() re-derives them, so walk 2 == walk 1 (proved in PART 1)",
      snapshots[0]["escalation_ids"] == snapshots[1]["escalation_ids"])

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — a single cut, re-run inside a period")
print("=" * 74)
cut_state = Path(tempfile.mkdtemp(prefix="cureva-t318-cut-"))
cut_crew = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=cut_state)
cut_watch = StudyWatch(DATA, cut_crew)
cut_watch.run_period(cuts=[5])
after_one = (len(cut_crew.memory.escalations), len(cut_crew.memory.queries_raised))
cut_watch.run_period(cuts=[5])
after_two = (len(cut_crew.memory.escalations), len(cut_crew.memory.queries_raised))
print(f"  cut 5 once : escalations={after_one[0]} queries={after_one[1]}")
print(f"  cut 5 twice: escalations={after_two[0]} queries={after_two[1]}")
check("re-running a single cut raises nothing new", after_one == after_two,
      f"{after_one} vs {after_two}")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — two cold walks in separate state dirs agree exactly")
print("=" * 74)
cold = []
for n in (1, 2):
    s = Path(tempfile.mkdtemp(prefix=f"cureva-t318-c{n}-"))
    c = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=s)
    wv = StudyWatch(DATA, c)
    r = wv.run_period(cuts=range(1, 13))
    cold.append(fingerprint(wv, r))
    print(f"  cold run {n}: escalations={cold[-1]['escalations']} "
          f"ids={cold[-1]['escalation_ids']} artifacts={cold[-1]['artifacts']}")
check("two independent cold walks produce identical escalation sets",
      cold[0]["escalation_ids"] == cold[1]["escalation_ids"])
check("  identical queries", cold[0]["query_keys"] == cold[1]["query_keys"])
check("  identical artifacts", cold[0]["artifacts"] == cold[1]["artifacts"])
check("  identical human-gate timing",
      cold[0]["asked_at"] == cold[1]["asked_at"])
check("  and a cold walk agrees with the warm first walk",
      cold[0]["escalation_ids"] == first["escalation_ids"],
      f"{cold[0]['escalation_ids']} vs {first['escalation_ids']}")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
