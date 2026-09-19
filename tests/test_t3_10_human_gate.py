"""T3.10 VERIFY — surviving a slow, unreliable reviewer across a period.

The T3.0 audit searched the organiser's materials for a time-aware reply
mechanism and found none: `study.escalate()` is a synchronous lookup over a
static table, and the same key returns the same answer at cut 1 and cut 12.
So PRD 4.3's fallback is what is built, and it is labelled as simulated
everywhere it surfaces.

What is real: every decision below came back from the study's own escalation
channel, and CLARIFY is resolved by Stage 2's own `_apply_decision`.
What is simulated: *when* the monitor is asked.

The requirement this test exists to protect is FR-9 — a cut passing must never
advance an escalation's state. PART 3 proves that directly.

Run: .venv/bin/python tests/test_t3_10_human_gate.py
"""
import logging
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def walk(cuts=range(1, 13), policy="delayed"):
    state = Path(tempfile.mkdtemp(prefix="cureva-t310-"))
    graph = StudyGraph(DATA)
    crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
    watch = StudyWatch(DATA, crew, escalation_policy=policy)
    return watch, watch.run_period(cuts=cuts)


# ==========================================================================
print("=" * 74)
print("PART 1 — the sampling rule matches the organiser's stated distribution")
print("=" * 74)
watch, report = walk()
records = watch.crew.memory.escalations
delays = Counter(watch._delay_for(e) for e in watch.memory.pending_queue)
total = sum(delays.values())
print(f"\n  {total} escalations raised over the period:")
targets = {2: 0.60, 4: 0.25, 10**6: 0.15}
for delay, count in sorted(delays.items()):
    label = "never" if delay >= 10**6 else f"{delay} cuts"
    print(f"      wait {label:>8}: {count:>4}  ({count / total:.1%})   "
          f"organiser's figure: {targets[delay]:.0%}")
for delay, target in targets.items():
    share = delays.get(delay, 0) / total
    check(f"  wait={'never' if delay >= 10**6 else delay}: {share:.1%} vs a "
          f"target of {target:.0%}", abs(share - target) < 0.05,
          f"{share:.1%}")

waits = {e: watch.memory.asked_at[e] - records[e].raised_cut
         for e in watch.memory.asked_at}
print(f"\n  actual waits before the monitor was asked: "
      f"{dict(sorted(Counter(waits.values()).items()))}")
check("no escalation was asked on the cut it was raised (that is the whole point)",
      all(w >= 2 for w in waits.values()), f"min wait {min(waits.values())}")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — FR-10: the four outcomes stay distinguishable")
print("=" * 74)
states = Counter("send_failed" if r.send_failed else r.state for r in records.values())
print(f"  {dict(states)}")
check("APPROVED and REJECTED are both present and are real monitor answers",
      states.get("APPROVED", 0) > 0 and states.get("REJECTED", 0) > 0,
      f"APPROVED={states.get('APPROVED')} REJECTED={states.get('REJECTED')}")
check("PENDING is present at period end", states.get("PENDING", 0) > 0,
      str(states.get("PENDING")))
check("  no PENDING escalation carries a decision",
      all(r.decision is None for r in records.values() if r.state == "PENDING"))
check("  every resolved escalation was genuinely asked first",
      all(e in watch.memory.asked_at for e, r in records.items()
          if r.state in ("APPROVED", "REJECTED")))

last_cut = 12
open_now = [e for e, due in watch.memory.pending_queue.items()
            if due > last_cut and records[e].state == "PENDING"]
never = [e for e in open_now if watch._delay_for(e) >= 10**6]
not_due = [e for e in open_now if watch._delay_for(e) < 10**6]
print(f"\n  of {len(open_now)} still open at period end:")
print(f"      {len(never):>4} the reviewer never answered")
print(f"      {len(not_due):>4} raised too close to the end to be due "
      f"(raised at cuts {sorted(set(records[e].raised_cut for e in not_due))})")
check("both causes of 'still open' are present and separable",
      len(never) > 0 and len(not_due) > 0)
check("  the report states them separately, not as one number",
      "went unanswered by the reviewer" in report.markdown
      and "too close to the end of the period" in report.markdown)

print("\n  a REAL escalation that resolved LATE:")
late = [e for e, w in waits.items() if w >= 4]
e = sorted(late)[0]
r = records[e]
print(f"      {e} {r.code} {r.usubjid or r.site}")
print(f"      raised at cut {r.raised_cut}, asked at cut {watch.memory.asked_at[e]}, "
      f"state={r.state}, decision={r.decision!r}")
print(f"      reason: {(r.reason or '')[:90]}")
check("  it carries the monitor's REAL words, not a placeholder",
      bool(r.reason) and "review page" not in (r.reason or ""), r.reason or "")

print("\n  a REAL escalation that was NEVER answered:")
e = sorted(never)[0]
r = records[e]
print(f"      {e} {r.code} {r.usubjid or r.site}")
print(f"      raised at cut {r.raised_cut}, would be asked at cut "
      f"{watch.memory.pending_queue[e]}, state={r.state}, decision={r.decision!r}")
check("  it ends the period PENDING with no decision", r.state == "PENDING"
      and r.decision is None)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — FR-9: a cut passing NEVER changes a state by itself")
print("=" * 74)
# Walk cut by cut and watch one never-answered escalation's state at every cut.
state2 = Path(tempfile.mkdtemp(prefix="cureva-t310-step-"))
graph2 = StudyGraph(DATA)
crew2 = ReviewCrew(DATA, Atlas(graph2), state_dir=state2)
step = StudyWatch(DATA, crew2, escalation_policy="delayed")
watched = None
history = []
for cut in range(1, 13):
    step.run_period(cuts=[cut])
    if watched is None:
        candidates = [e for e, due in step.memory.pending_queue.items()
                      if due >= 10**6]
        watched = sorted(candidates)[0] if candidates else None
    if watched:
        rec = crew2.memory.escalations[watched]
        history.append((cut, rec.state, rec.decision))
print(f"  tracking {watched} across every cut of the period:")
for cut, state, decision in history:
    print(f"      after cut {cut:>2}: state={state:<9} decision={decision!r}")
check("its state is PENDING at every single cut, start to finish",
      all(s == "PENDING" for _c, s, _d in history), 
      str(sorted(set(s for _c, s, _d in history))))
check("  it never acquires a decision merely because cuts passed",
      all(d is None for _c, _s, d in history))

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — FR-11/FR-12: CLARIFY reuses Stage 2, and a re-walk is stable")
print("=" * 74)
clarified = [r for r in records.values() if r.clarify_count > 0]
print(f"  escalations that went through CLARIFY: {len(clarified)}")
if clarified:
    r = clarified[0]
    print(f"      {r.escalation_id} {r.code}: clarify_count={r.clarify_count} "
          f"state={r.state}")
    print(f"      reason: {(r.reason or '')[:110]}")
check("CLARIFY was exercised for real", len(clarified) > 0, f"{len(clarified)}")
check("  and resolved through Stage 2's documented resubmission rule",
      all(r.state in ("APPROVED", "REJECTED") for r in clarified))
check("  the reason carries the monitor's REAL question",
      all("?" in (r.reason or "") for r in clarified))
check("  and no escalation is mislabelled as 'decided on the review page' "
      "— nobody clicked anything; the period walk asked",
      not any("decided on the review page" in (r.reason or "")
              for r in records.values()))
check("  ...while still naming the cut the question was actually put at",
      all("asked by the period walk at cut" in (r.reason or "") for r in clarified))

w2, r2 = walk()
a = sorted((e, records[e].state, records[e].decision) for e in records)
b = sorted((e, w2.crew.memory.escalations[e].state,
            w2.crew.memory.escalations[e].decision)
           for e in w2.crew.memory.escalations)
check("a cold re-walk resolves EXACTLY the same escalations the same way",
      a == b, f"{len(a)} vs {len(b)}")
check("  and asks each one at exactly the same cut",
      watch.memory.asked_at == w2.memory.asked_at,
      f"{len(watch.memory.asked_at)} vs {len(w2.memory.asked_at)}")

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — honesty: the report says which half is simulated")
print("=" * 74)
for phrase in ("The monitor's decisions are real",
               "What is simulated, and stated as such",
               "is Cureva's own policy, not the organiser's behaviour",
               "never treated as approval"):
    check(f"report states: {phrase!r}", phrase in report.markdown)

immediate_watch, immediate_report = walk(policy="immediate")
imm = Counter(r.state for r in immediate_watch.crew.memory.escalations.values())
print(f"\n  for comparison, escalation_policy='immediate' (Stage 2's own behaviour): "
      f"{dict(imm)}")
check("the immediate policy resolves everything inline, as Stage 2 always did",
      imm.get("PENDING", 0) == 0, f"{imm.get('PENDING', 0)} pending")
check("  so the difference between the two is demonstrable, not asserted",
      states.get("PENDING", 0) > 0 and imm.get("PENDING", 0) == 0)
check("  and the caller's crew is handed back with its own setting intact",
      immediate_watch.crew.human_gate == "auto", immediate_watch.crew.human_gate)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
