"""T2.11 VERIFY — the same cut, reviewed twice, raises nothing new.

This is the single most load-bearing property in Stage 2 (PRD G2/FR-16,
NFR-5). A reviewer that re-queries records it already queried, or re-escalates
findings a monitor already answered, is worse than a slow human: it buries the
real signal under its own repetitions.

The test asserts three things about a second `run_cycle()` over the same cut:
memory does not grow, no `query_raised`/`escalation_raised` trace lines are
written, and the report's own content is unchanged. It then re-runs the whole
check with the dedup guards monkey-patched off, and requires that it *fails* --
a test that cannot fail proves nothing.
"""
import os
import shutil
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from stage2 import ReviewCrew
from stage2.memory import CrewMemory

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")
CUT, PROTOCOL_VERSION = 9, 3

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def run_twice(state_dir, break_dedup=False):
    """Two cycles over the same cut. Returns what changed between them."""
    graph = StudyGraph(DATA_DIR)
    crew = ReviewCrew(DATA_DIR, Atlas(graph), state_dir=state_dir)

    if break_dedup:
        # Exactly the guards T2.6 and T2.8 rely on, switched off. Nothing else
        # changes, so a failure here is attributable to the dedup and to
        # nothing else in the cycle.
        crew.memory.has_query = lambda key: False
        crew.memory.has_escalation = lambda esc_id: False

    first = crew.run_cycle(cut=CUT, protocol_version=PROTOCOL_VERSION)
    sizes_before = dict(crew.memory.sizes())

    second = crew.run_cycle(cut=CUT, protocol_version=PROTOCOL_VERSION)
    sizes_after = dict(crew.memory.sizes())
    second_types = Counter(e.decision_type for e in crew.trace.current_cycle)

    return {
        "sizes_before": sizes_before,
        "sizes_after": sizes_after,
        "new_queries": second_types.get("query_raised", 0),
        "new_escalations": second_types.get("escalation_raised", 0),
        "skipped_queries": second_types.get("query_skipped_duplicate", 0),
        "skipped_escalations": second_types.get("escalation_skipped_duplicate", 0),
        "first": first,
        "second": second,
    }


print(f"=== T2.11 — repeat cycle over cut {CUT} raises nothing new ===\n")

work = tempfile.mkdtemp(prefix="cureva-t2-11-")
try:
    r = run_twice(os.path.join(work, "real"))

    print(f"memory after cycle 1: {r['sizes_before']}")
    print(f"memory after cycle 2: {r['sizes_after']}")
    print(f"cycle 2 trace: {r['new_queries']} query_raised, "
          f"{r['new_escalations']} escalation_raised, "
          f"{r['skipped_queries']} query_skipped_duplicate, "
          f"{r['skipped_escalations']} escalation_skipped_duplicate\n")

    check("memory sizes are unchanged by the second cycle",
          r["sizes_before"] == r["sizes_after"])
    check("second cycle raises zero new queries",
          r["new_queries"] == 0, f"(raised {r['new_queries']})")
    check("second cycle raises zero new escalations",
          r["new_escalations"] == 0, f"(raised {r['new_escalations']})")
    check("the second cycle actually did the work and skipped on purpose",
          r["skipped_queries"] > 0 and r["skipped_escalations"] > 0,
          f"({r['skipped_queries']} queries, {r['skipped_escalations']} escalations skipped)")
    check("both cycles report the same findings",
          [f.fingerprint() for f in r["first"].findings]
          == [f.fingerprint() for f in r["second"].findings])
    check("both cycles report the same queries",
          {q.id for q in r["first"].queries} == {q.id for q in r["second"].queries})
    check("both cycles report the same escalations",
          {e.id for e in r["first"].escalations} == {e.id for e in r["second"].escalations})
    check("the verdicts do not drift between cycles",
          [f.code for f in r["first"].deviations] == [f.code for f in r["second"].deviations])

    # ------------------------------------------------------------------
    # The harder case: a repeat AFTER a multi-cut walk.
    #
    # The single-cut check above passed for weeks while memory was still
    # mutating. Walking cuts 1..12 first lets the serious-AE watch fill, fire
    # and clear; only then does repeating the last cut expose whether anything
    # re-populates. It did -- the watch oscillated 0 -> 5 -> 0 -- and nothing
    # here caught it, because a fresh crew at one cut never reaches that state.
    # ------------------------------------------------------------------
    print("\n=== a repeat after walking every cut ===\n")
    walk_dir = os.path.join(work, "walk")
    walk_graph = StudyGraph(DATA_DIR)
    walk_crew = ReviewCrew(DATA_DIR, Atlas(walk_graph), state_dir=walk_dir)
    for cut in range(1, 13):
        walk_crew.run_cycle(cut=cut,
                            protocol_version=walk_graph.protocol_version_at(cut))
    walk_before = dict(walk_crew.memory.sizes())
    walk_crew.run_cycle(cut=12, protocol_version=walk_graph.protocol_version_at(12))
    walk_after = dict(walk_crew.memory.sizes())
    walk_types = Counter(e.decision_type for e in walk_crew.trace.current_cycle)

    print(f"memory after the walk : {walk_before}")
    print(f"memory after a repeat : {walk_after}")
    changed = {k: (walk_before[k], walk_after[k])
               for k in walk_before if walk_before[k] != walk_after[k]}
    print(f"changed               : {changed or 'nothing'}\n")

    check("every memory counter is unchanged by a repeat after the full walk",
          walk_before == walk_after, f"(changed: {changed})")
    check("the repeat after the walk raises zero new queries",
          walk_types.get("query_raised", 0) == 0)
    check("the repeat after the walk raises zero new escalations",
          walk_types.get("escalation_raised", 0) == 0)

    # ------------------------------------------------------------------
    # The same check, with the dedup guards removed. It must fail.
    # ------------------------------------------------------------------
    print("\n=== the same check with the dedup guards switched off ===\n")
    broken = run_twice(os.path.join(work, "broken"), break_dedup=True)
    print(f"memory after cycle 1: {broken['sizes_before']}")
    print(f"memory after cycle 2: {broken['sizes_after']}")
    print(f"cycle 2 trace: {broken['new_queries']} query_raised, "
          f"{broken['new_escalations']} escalation_raised\n")

    would_have_failed = (broken["new_queries"] > 0
                         or broken["new_escalations"] > 0)
    check("without the dedup guards the property genuinely breaks",
          would_have_failed,
          f"({broken['new_queries']} queries and {broken['new_escalations']} "
          f"escalations re-raised)")
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("ALL T2.11 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
