"""T3.5 VERIFY — the one additive `ReviewCrew` method, and the regression that matters.

This is the hardest stop in the Stage 3 build document, and for a specific
reason: `stage2/crew.py` is the only pre-existing file this stage changes at
all, and Stage 2 is separately graded. A refactor that quietly altered
`run_cycle()`'s own output would fail Stage 2's grading, and would be
discovered long after the fact.

So (a) is not an assertion about the refactor — it is a real before/after
comparison. The pre-change `stage2/crew.py` is recovered from git into a
separate tree, a real cycle is run in a separate interpreter against each, and
the two `ReviewReport`s are diffed. Importing two versions of one module into a
single process would prove nothing, so it is deliberately not done that way.

Three fields are normalised because they are nondeterministic by design: a
uuid4 trace id, a wall-clock timestamp, and elapsed milliseconds (including the
copy of it that EXECUTE interpolates into its own summary text). Every finding,
escalation, query, deviation and every other trace line is compared verbatim.

Run: .venv/bin/python tests/test_t3_5_extra_findings.py
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Finding, RecordRef
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew

logging.basicConfig(level=logging.CRITICAL)

REPO = Path(__file__).resolve().parent.parent
DATA = str(REPO / "hackathon-data")
PY_EXE = sys.executable
RUNNER = REPO / "tests" / "_t3_5_runner.py"
CUTS = (1, 3, 5, 9, 12)

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


# ==========================================================================
print("=" * 74)
print("(a) REGRESSION — run_cycle()'s output before vs after the refactor")
print("=" * 74)

orig = Path(tempfile.mkdtemp(prefix="cureva-t35-head-")) / "head"
orig.mkdir(parents=True)
archive = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, capture_output=True)
subprocess.run(["tar", "-x", "-C", str(orig)], input=archive.stdout, check=True)
shutil.copytree(REPO / "hackathon-data", orig / "hackathon-data", dirs_exist_ok=True)
(orig / "tests").mkdir(exist_ok=True)
shutil.copy(RUNNER, orig / "tests" / RUNNER.name)

head_crew = (orig / "stage2" / "crew.py").read_text()
live_crew = (REPO / "stage2" / "crew.py").read_text()
check("the pre-change crew.py really is different (otherwise this proves nothing)",
      head_crew != live_crew,
      f"HEAD {len(head_crew)} chars, working tree {len(live_crew)} chars")
check("  run_cycle_with_extra_findings exists now and did not before",
      "run_cycle_with_extra_findings" in live_crew
      and "run_cycle_with_extra_findings" not in head_crew)


def run_cycle_json(repo: Path, cut: int) -> str:
    state = tempfile.mkdtemp(prefix="cureva-t35-state-")
    out = subprocess.run([PY_EXE, str(repo / "tests" / RUNNER.name), str(repo),
                          str(cut), state],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"runner failed in {repo}: {out.stderr[-800:]}")
    return out.stdout


print()
for cut in CUTS:
    before, after = run_cycle_json(orig, cut), run_cycle_json(REPO, cut)
    check(f"cut {cut:>2}: run_cycle() output is byte-identical (empty diff)",
          before == after, f"{len(before):>9,} bytes")
    if before != after:
        import difflib
        for line in list(difflib.unified_diff(before.splitlines(),
                                              after.splitlines(), lineterm=""))[:20]:
            print(f"        {line}")

# ==========================================================================
print()
print("=" * 74)
print("(b) THE NEW METHOD — an extra finding joins the pipeline as a peer")
print("=" * 74)

CUT = 6
state = Path(tempfile.mkdtemp(prefix="cureva-t35-new-"))
crew = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=state)
version = crew.graph.protocol_version_at(CUT)

baseline = crew.run_cycle(CUT, version)
print(f"  baseline run_cycle(cut={CUT}): {len(baseline.findings)} finding(s), "
      f"{len(baseline.escalations)} escalation(s), {len(baseline.deviations)} deviation(s)")

# A synthetic Stage-3-shaped finding, built from a REAL record so its evidence
# is citable. LAB_UNIT_CORRUPTION is one of the four codes this stage owns and
# is exactly the kind of cut-over-cut finding this seam exists to carry.
crew.graph.build(CUT)
real_lb = next(r for r in crew.graph.records("LB", cut=CUT)
               if r.get("LBTESTCD") == "GLUC")
subject = real_lb["USUBJID"]
extra = Finding(
    code="LAB_UNIT_CORRUPTION",
    usubjid=subject,
    site=crew.graph.site_for(subject),
    severity="HIGH",
    rationale="SYNTHETIC T3.5 probe finding — exercises the extra-findings seam.",
    evidence=[Atlas.ref(real_lb)],
    confidence=0.9,
)
print(f"  injecting one synthetic {extra.code} for {subject} "
      f"(evidence: LB seq {extra.evidence[0].seq})")

state2 = Path(tempfile.mkdtemp(prefix="cureva-t35-new2-"))
crew2 = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=state2)
with_extra = crew2.run_cycle_with_extra_findings(CUT, version, [extra])

print(f"  run_cycle_with_extra_findings: {len(with_extra.findings)} finding(s), "
      f"{len(with_extra.escalations)} escalation(s), "
      f"{len(with_extra.deviations)} deviation(s)")

fingerprints = {f.fingerprint() for f in with_extra.findings}
check("the extra finding appears in the report's findings",
      extra.fingerprint() in fingerprints)
check("  exactly one extra finding relative to the baseline",
      len(with_extra.findings) == len(baseline.findings) + 1,
      f"{len(baseline.findings)} -> {len(with_extra.findings)}")
check("  every baseline finding is still present (nothing displaced)",
      {f.fingerprint() for f in baseline.findings} <= fingerprints)

verdict = next((v for v in crew2.last_verdicts
                if v.finding.fingerprint() == extra.fingerprint()), None)
check("MEDICAL REVIEW produced a real verdict for it (it ran through the node)",
      verdict is not None,
      f"rule={verdict.rule!r} escalate={verdict.escalate}" if verdict else "no verdict")

esc_ids = {e.id for e in with_extra.escalations}
from stage2.crew import escalation_id_for                      # noqa: E402
check("  ...and HUMAN GATE acted on that verdict, reaching a real decision",
      escalation_id_for(extra) in esc_ids if (verdict and verdict.escalate) else True,
      f"escalation {escalation_id_for(extra)} present: {escalation_id_for(extra) in esc_ids}")
if escalation_id_for(extra) in esc_ids:
    out = next(e for e in with_extra.escalations if e.id == escalation_id_for(extra))
    print(f"      decision={out.decision!r} reason={(out.reason or '')[:70]!r}")

traced = [line for line in with_extra.trace
          if "cross-cut finding(s) supplied by StudyWatch" in line.get("summary", "")]
check("DETECT wrote a trace line recording where the extra finding came from",
      len(traced) == 1, traced[0]["summary"] if traced else "no line")

base_trace = [line for line in baseline.trace
              if "cross-cut finding(s) supplied by StudyWatch" in line.get("summary", "")]
check("  ...and run_cycle() with no extras writes no such line at all",
      len(base_trace) == 0)

empty = ReviewCrew(DATA, Atlas(StudyGraph(DATA)),
                   state_dir=Path(tempfile.mkdtemp(prefix="cureva-t35-empty-"))
                   ).run_cycle_with_extra_findings(CUT, version, [])
check("run_cycle_with_extra_findings(..., []) == run_cycle() finding-for-finding",
      {f.fingerprint() for f in empty.findings} == {f.fingerprint() for f in baseline.findings},
      f"{len(empty.findings)} vs {len(baseline.findings)}")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
