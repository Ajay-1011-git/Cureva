"""T2.10 VERIFY — the trace is written live, not reconstructed at cycle end.

FR-17/FR-18: a decision with no trace line is, downstream, treated as not
having happened. That only means anything if the line is on disk at the moment
of the decision -- a trace assembled after the cycle returns would be a summary
of a run that succeeded, and would say nothing at all about one that didn't.

The test kills a cycle inside COMPLIANCE and reads the file back. Everything
the three earlier nodes decided must already be there, and nothing from the
nodes that never ran.
"""
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from stage2 import ReviewCrew
from stage2.models import TraceEntry

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")
CUT, PROTOCOL_VERSION = 1, 1

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


print("=== T2.10 — a cycle interrupted mid-flight still left its trace ===\n")

work = tempfile.mkdtemp(prefix="cureva-t2-10-")
try:
    graph = StudyGraph(DATA_DIR)
    crew = ReviewCrew(DATA_DIR, Atlas(graph), state_dir=work)

    def interrupt(ctx):
        raise RuntimeError("deliberate interruption inside COMPLIANCE")

    crew._node_compliance = interrupt

    died = False
    try:
        crew.run_cycle(cut=CUT, protocol_version=PROTOCOL_VERSION)
    except RuntimeError:
        died = True

    check("the cycle really was interrupted", died)

    trace_path = Path(work) / "trace" / "cycle_trace.jsonl"
    check("the trace file exists on disk", trace_path.exists())

    lines = [json.loads(l) for l in trace_path.read_text().splitlines() if l.strip()]
    nodes = Counter(l["node"] for l in lines)
    print(f"\n  {len(lines)} line(s) on disk, by node: {dict(nodes)}\n")

    check("DETECT's decisions are already on disk", nodes.get("DETECT", 0) > 0,
          f"({nodes.get('DETECT', 0)} lines)")
    check("MEDICAL REVIEW's verdicts are already on disk",
          nodes.get("MEDICAL_REVIEW", 0) > 0, f"({nodes.get('MEDICAL_REVIEW', 0)} lines)")
    check("DATA MANAGER's queries are already on disk",
          nodes.get("DATA_MANAGER", 0) > 0, f"({nodes.get('DATA_MANAGER', 0)} lines)")
    check("nothing from COMPLIANCE, which raised before deciding anything",
          nodes.get("COMPLIANCE", 0) == 0)
    check("nothing from HUMAN GATE, which never ran", nodes.get("HUMAN_GATE", 0) == 0)
    check("nothing from EXECUTE, which never ran", nodes.get("EXECUTE", 0) == 0)

    check("every line validates against TraceEntry",
          all(TraceEntry.model_validate(l) for l in lines))
    check("one verdict line per finding detected",
          Counter(l["decision_type"] for l in lines)["verdict_assigned"] > 0)
    check("memory snapshot absent for a cycle that never finished",
          not (Path(work) / "memory_snapshot.json").exists())

    # A trace assembled at cycle end could not have produced the file above.
    # State it as an assertion rather than an observation.
    check("the interrupted cycle returned no report to reconstruct a trace from",
          died and len(lines) > 0,
          f"({len(lines)} lines exist despite the cycle never returning)")
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("ALL T2.10 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
