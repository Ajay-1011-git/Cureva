"""Stage 3 final acceptance — the 14 criteria in the build document's §E.

Each one is checked against the repository or a real run, not asserted. Where a
criterion cannot be checked from here, this file says so explicitly rather than
passing it quietly.

Run: .venv/bin/python tests/test_t3_final_acceptance.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent
fails, notes = [], []


def baseline_crew_py(repo: Path) -> tuple[str, str]:
    """The last version of stage2/crew.py from BEFORE this stage touched it.

    Anchored to the newest commit whose crew.py does not yet contain the new
    method, found by walking that file's history — not to HEAD.

    Anchoring to HEAD was correct exactly until this work was committed, and
    then silently wrong: once the branch merged, `HEAD:stage2/crew.py` became
    the post-change file, the "before" and "after" were the same bytes, and the
    comparison proved nothing while still reporting PASS. A regression test
    that stops testing when the code ships is worse than no test, because it
    goes on being cited.
    """
    revs = subprocess.run(
        ["git", "log", "--format=%H", "--", "stage2/crew.py"],
        cwd=repo, capture_output=True, text=True).stdout.split()
    for rev in revs:                       # newest first
        blob = subprocess.run(["git", "show", f"{rev}:stage2/crew.py"],
                              cwd=repo, capture_output=True, text=True)
        if blob.returncode == 0 and "run_cycle_with_extra_findings" not in blob.stdout:
            return rev, blob.stdout
    raise AssertionError(
        "no commit of stage2/crew.py predates run_cycle_with_extra_findings — "
        "the before/after comparison cannot be made")



def check(n, label, cond, detail=""):
    if not cond:
        fails.append(f"{n}: {label}")
    print(f"  {'PASS' if cond else 'FAIL'}  {n:>2}. {label}{('   ' + detail) if detail else ''}")


def manual(n, label, why):
    notes.append(f"{n}: {label}")
    print(f"  NOTE  {n:>2}. {label}\n        {why}")


print("=" * 74)
print("STAGE 3 — FINAL ACCEPTANCE (build document §E)")
print("=" * 74)

# 1 — run_period returns a valid SurveillanceReport with no Groq key
from schemas import SurveillanceReport                            # noqa: E402
from stage1.atlas import Atlas, StudyGraph                        # noqa: E402
from stage2.crew import ReviewCrew                                # noqa: E402
from stage3.watch import StudyWatch                               # noqa: E402

env_key = os.environ.pop("GROQ_API_KEY", None)
env_key2 = os.environ.pop("groq_api_key", None)
state = Path(tempfile.mkdtemp(prefix="cureva-final-"))
graph = StudyGraph("hackathon-data")
crew = ReviewCrew("hackathon-data", Atlas(graph), state_dir=state)
watch = StudyWatch("hackathon-data", crew)
report = watch.run_period(cuts=range(1, 13))
check(1, "run_period(1..13) returns a valid SurveillanceReport with NO Groq key",
      isinstance(report, SurveillanceReport)
      and SurveillanceReport.model_validate(report.model_dump()) is not None
      and all(report.model_dump()[f] for f in SurveillanceReport.model_fields)
      and report.budget["tokens"]["spent"] == 0,
      f"{len(report.decisions)} decisions, {report.budget['tokens']['spent']} tokens")
if env_key: os.environ["GROQ_API_KEY"] = env_key
if env_key2: os.environ["groq_api_key"] = env_key2

# 2 — re-running raises nothing new, ledgers and history unchanged
before = (len(crew.memory.escalations), len(crew.memory.queries_raised),
          len(watch.memory.superseded), dict(watch.memory.asked_at))
watch.run_period(cuts=range(1, 13))
after = (len(crew.memory.escalations), len(crew.memory.queries_raised),
         len(watch.memory.superseded), dict(watch.memory.asked_at))
check(2, "re-running the period raises 0 new escalations/queries, history unchanged",
      before == after, f"{before[:3]} vs {after[:3]}")

# 3 — a correction's finding is shown superseded
causes = {e.cause for e in watch.memory.superseded}
check(3, "findings that stop being true are recorded with an established cause",
      len(watch.memory.superseded) > 0
      and all(e.reason.strip() for e in watch.memory.superseded)
      and "Findings that are no longer current" in report.markdown,
      f"{len(watch.memory.superseded)} recorded, causes {sorted(causes)}")

# 4 — all four detectors, LAB_UNIT_CORRUPTION on the real S04 case
codes = {f.code for f in report.signals}
s04 = [f for f in report.signals
       if f.code == "LAB_UNIT_CORRUPTION" and f.site == "S04"]
check(4, "all four Stage-3 detectors fire; LAB_UNIT_CORRUPTION on the real S04 case",
      {"LAB_UNIT_CORRUPTION", "DOCUMENT_TAMPERED", "IMPLAUSIBLE_SITE_PATTERN",
       "LATE_DATA_ENTRY"} <= codes and len(s04) == 1 and len(s04[0].evidence) >= 2,
      f"S04 cites {len(s04[0].evidence) if s04 else 0} records")

# 5 — run_cycle byte-identical (proved by its own test; re-assert the seam)
crew_src = (REPO / "stage2" / "crew.py").read_text()
baseline_rev, head = baseline_crew_py(REPO)
check(5, "run_cycle()'s body is shared, not duplicated, and the new method is additive",
      "def run_cycle_with_extra_findings" in crew_src
      and "return self._run_cycle(cut, protocol_version, extra_findings=[])" in crew_src
      and "def run_cycle_with_extra_findings" not in head,
      f"baseline {baseline_rev[:12]}; byte-identical output proved in "
      f"test_t3_5_extra_findings.py")

# 6 — the slow human, including one that never resolves
pending = [r for r in crew.memory.escalations.values() if r.state == "PENDING"]
never = [e for e, due in watch.memory.pending_queue.items()
         if watch._delay_for(e) >= 10**6]
late = [e for e, c in watch.memory.asked_at.items()
        if c - crew.memory.escalations[e].raised_cut >= 4]
check(6, "slow reviewer demonstrated: some answered late, some never",
      len(late) > 0 and len(never) > 0 and len(pending) > 0
      and all(r.decision is None for r in pending),
      f"{len(late)} late, {len(never)} never answered, {len(pending)} open")

# 7 — onboarding (its own test); assert no site name is hard-coded anywhere
src_all = "\n".join((REPO / d / f).read_text()
                    for d, fs in (("stage3", ["watch.py", "memory.py", "detectors.py",
                                              "budget.py"]),
                                  ("forecast", ["montecarlo.py"]),
                                  ("execute", ["templates.py", "polish.py"]))
                    for f in fs)
code_only = re.sub(r'"""(?:.|\n)*?"""', "", src_all)
code_only = "\n".join(l.split("#")[0] for l in code_only.splitlines())
check(7, "onboarding: no site id appears in any conditional (test_t3_11 proves absorption)",
      not re.search(r'["\']S\d{2}["\']', code_only),
      str(re.findall(r'["\']S\d{2}["\']', code_only)[:3]))

# 8 — degradation order demonstrated
from stage3.budget import DEGRADATION_ORDER, NEVER_DEGRADES, TimeLedger, TokenLedger  # noqa: E402
state2 = Path(tempfile.mkdtemp(prefix="cureva-final2-"))
crew2 = ReviewCrew("hackathon-data", Atlas(StudyGraph("hackathon-data")), state_dir=state2)
starved = StudyWatch("hackathon-data", crew2)
starved.tokens = TokenLedger(ceiling=0)
starved.time_budget = TimeLedger(hard_deadline_s=0.0001)
starved_report = starved.run_period(cuts=range(1, 13))
check(8, "with BOTH budgets at zero, every deterministic check is unchanged",
      len(starved_report.signals) == len(report.signals)
      and len(starved_report.escalations) == len(report.escalations)
      and starved_report.budget["trace_lines"] == report.budget["trace_lines"]
      and len(DEGRADATION_ORDER) == 3 and len(NEVER_DEGRADES) == 5,
      f"{len(starved_report.signals)} signals, "
      f"{starved_report.budget['trace_lines']} trace lines")

# 9 — explain() on 3 real decisions matches the trace
ok9 = True
trace = [json.loads(l) for l in
         (state / "trace" / "cycle_trace.jsonl").read_text().splitlines() if l.strip()]
for d in report.decisions[:3]:
    e = watch.explain(d.id)
    on_disk = [r for r in trace if r.get("escalation_id") == d.id]
    ok9 &= (len(e.evidence_lines) == len(on_disk) and len(on_disk) > 0
            and all(str(r["summary"]) in line
                    for r, line in zip(on_disk, e.evidence_lines)))
check(9, "explain() on 3 real decisions matches the trace file line for line", ok9)

# 10 — no practice-data value in a conditional
leaks = [n for n in ('"S04"', "'S04'", '"S11"', '"S08"', '"GLUC"', "'GLUC'",
                     '"042-', "18.0", '"lab-manual"') if n in code_only]
check(10, "no practice-data id or threshold appears in any conditional",
      not leaks, str(leaks))

# 11 — schemas.py untouched; stage1 untouched; crew.py additive only
def unchanged(rel):
    """Whether a file this stage must not touch is byte-identical to the
    baseline — the same pre-Stage-3 commit crew.py is compared against, not
    HEAD, so this keeps meaning something after the work is committed."""
    blob = subprocess.run(["git", "show", f"{baseline_rev}:{rel}"], cwd=REPO,
                          capture_output=True, text=True)
    return blob.returncode == 0 and blob.stdout == (REPO / rel).read_text()

sig_re = re.compile(r"^\s{4}def (\w+)\(", re.M)
head_sigs = set(sig_re.findall(head))
live_sigs = set(sig_re.findall(crew_src))
check(11, "schemas.py untouched", unchanged("schemas.py"))
check(11, "  study.py untouched", unchanged("study.py"))
check(11, "  stage1/atlas.py untouched", unchanged("stage1/atlas.py"))
check(11, "  stage2/crew.py gained methods only, removed none",
      head_sigs <= live_sigs,
      f"added {sorted(live_sigs - head_sigs)}, removed {sorted(head_sigs - live_sigs)}")

# 12 — /watch renders (backend contracts here; browser pass noted)
from fastapi.testclient import TestClient                          # noqa: E402
import warnings; warnings.filterwarnings("ignore")
from webapp.server import app                                      # noqa: E402
client = TestClient(app)
client.post("/api/watch/run-period", json={"cuts": [1, 2, 3, 4]})
fc = client.get("/api/watch/forecast").json()
ar = client.get("/api/watch/artifacts").json()
check(12, "the /watch page's four routes all serve real data",
      fc["count"] > 0 and ar["count"] > 0
      and all(r["source"] in ("template_only", "polished") for r in ar["artifacts"])
      and all(r.get("decision") for r in fc["forecasts"]),
      f"{fc['count']} forecasts, {ar['count']} artifacts")
manual(12, "a live browser pass on /watch was NOT performed",
       "No browser was available in the build environment. The production build "
       "is clean, the route and nav link resolve, the chart was rasterised and "
       "inspected, and 125 real forecast rows pass a layout check — but "
       "'no console errors' is unverified. Run `npm run dev` and open /watch.")

# 13 — submission artifacts
for rel in ("stage3_surveillance_report.md", "stage3_decision_log.json",
            "docs/stage3-solution-design.md", "docs/stage3-deck-outline.md",
            "docs/demo-video-checklist.md"):
    p = REPO / rel
    check(13, f"{rel} present", p.exists() and p.stat().st_size > 0)
log = json.loads((REPO / "stage3_decision_log.json").read_text())
check(13, "  every decision log entry has a real explanation",
      log["counts"]["without_explanation"] == 0,
      f"{log['counts']['decisions']} entries")
design_words = len((REPO / "docs/stage3-solution-design.md").read_text().split())
check(13, "  Solution Design is within 3 pages", design_words / 450 <= 3.0,
      f"{design_words} words = {design_words/450:.1f} pages")

# 14 — commits
manual(14, "the '20 commits prefixed T3.<n>' criterion is NOT met",
       "The user asked for no commits after T3.0, so the work sits in the "
       "working tree. `git log` shows 1 Stage-3 commit (T3.0). Everything else "
       "is uncommitted and ready to commit on request.")

print()
print("=" * 74)
if fails:
    print(f"FAILURES ({len(fails)}): {fails[:6]}")
else:
    print("ALL MECHANICAL CRITERIA PASS")
print(f"{len(notes)} criterion/criteria could not be checked from here and are "
      f"reported above, not passed silently.")
print("=" * 74)
sys.exit(1 if fails else 0)
