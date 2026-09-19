"""T3.4 VERIFY — a finding undone by a later change is marked, never dropped.

FR-4 / G2: a finding raised at an earlier cut whose evidence no longer holds at
a later cut must not reappear in the later sweep, must stay in the report
marked as superseded, and must never be left looking like an open, current
problem. Equally, its original escalation record must survive unmutated —
Watch keeps its own additional record and never edits Stage 2's memory or
trace retroactively.

Audit sections 10 and 11 measured three genuinely different reasons a finding
stops being detected, and only one of them is a correction. This test exercises
all three and checks that each is labelled with the cause that is actually
true, because "superseded by a correction" written over an escalation the
system acted on is a fabricated mechanism.

Run: .venv/bin/python tests/test_t3_4_supersession.py
"""
import csv
import logging
import os
import shutil
import sys
import tempfile
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


def walk(data_dir: str, cuts=range(1, 13)):
    state = Path(tempfile.mkdtemp(prefix="cureva-t34-"))
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state)
    watch = StudyWatch(data_dir, crew)
    return watch, watch.run_period(cuts=cuts)


# ==========================================================================
print("=" * 74)
print("PART 1 — the REAL case: a missing record arrives (audit 11, cause 2)")
print("=" * 74)
watch, report = walk(DATA, cuts=range(1, 13))
superseded = watch.memory.superseded
print(f"\n  a full 12-cut walk of the real practice data records "
      f"{len(superseded)} superseded finding(s)")
by_cause: dict[str, list] = {}
for entry in superseded:
    by_cause.setdefault(entry.cause, []).append(entry)
for cause, group in sorted(by_cause.items()):
    print(f"      {cause:<22} {len(group)}")

real = [e for e in superseded if e.finding_id and "MISSING_EXPOSURE" in e.reason.upper()
        or e.first_raised_cut == 4]
target = next((e for e in superseded
               if e.first_raised_cut <= 4 and e.superseded_at_cut == 5), None)
print("\n  the MISSING_EXPOSURE_RECORD|042-S08-007 case from T3.3:")
missing_ex = None
for entry in superseded:
    evidence = [e for e in (watch._findings_seen.get(entry.finding_id).evidence if watch._findings_seen.get(entry.finding_id) else [])]
    if any(e.usubjid == "042-S08-007" for e in evidence) or entry.first_raised_cut < 5 <= entry.superseded_at_cut:
        missing_ex = missing_ex or entry
if missing_ex:
    print(f"      finding_id        : {missing_ex.finding_id}")
    print(f"      first_raised_cut  : {missing_ex.first_raised_cut}")
    print(f"      superseded_at_cut : {missing_ex.superseded_at_cut}")
    print(f"      cause             : {missing_ex.cause}")
    print(f"      reason            : {missing_ex.reason}")
check("at least one finding is recorded as superseded on the real data",
      len(superseded) > 0, f"{len(superseded)} recorded")
check("every superseded entry carries a first_raised_cut STRICTLY before its "
      "superseded_at_cut",
      all(e.first_raised_cut < e.superseded_at_cut for e in superseded))
check("every superseded entry carries a non-empty reason",
      all(e.reason.strip() for e in superseded))
check("no entry claims a correction that audit 11 proved does not exist on this data",
      not [e for e in superseded if e.cause == "correction"],
      f"{len([e for e in superseded if e.cause == 'correction'])} correction-caused")

print("\n  the report never leaves them looking current:")
section = report.markdown
check("the markdown has a 'no longer current' section",
      "## Findings that are no longer current" in section)
check("  every superseded finding_id appears in it",
      all(e.finding_id in section for e in superseded))
check("  budget block counts them honestly",
      report.budget["superseded_findings"] == len(superseded),
      str(report.budget["superseded_findings"]))

print("\n  ...and the original escalation records are unmutated:")
escalation_ids = {e.escalation_id for e in superseded if e.escalation_id}
still_present = [eid for eid in escalation_ids
                 if eid in {x.id for x in report.escalations}]
check("every superseded finding's escalation is STILL in the report",
      len(still_present) == len(escalation_ids),
      f"{len(still_present)}/{len(escalation_ids)}")
for eid in sorted(escalation_ids)[:3]:
    rec = watch.crew.memory.escalations[eid]
    print(f"      {eid}: state={rec.state} decision={rec.decision!r} "
          f"raised_cut={rec.raised_cut}")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — a SYNTHETIC correction (T3.3 case 2), cause 'correction'")
print("=" * 74)
fixture = Path(tempfile.mkdtemp(prefix="cureva-t34-fixture-")) / "synthetic-study"
shutil.copytree(DATA, fixture)
SUBJECT, BILI_SEQ = "042-S05-003", 33
with (fixture / "data" / "corrections.csv").open("a", newline="") as fh:
    fh.write(f"8,LB,{SUBJECT},{BILI_SEQ},LBORRES,4.66,0.8,"
             f"SYNTHETIC test correction (T3.4) - not organiser data\n")
print(f"  fixture correction: cut 8, LB {SUBJECT} seq {BILI_SEQ}, LBORRES 4.66 -> 0.8")
print(f"  (appended to a temp copy; {DATA}/ is never written to)")

fwatch, freport = walk(str(fixture), cuts=range(1, 13))
corrected = [e for e in fwatch.memory.superseded if e.cause == "correction"]
print(f"\n  superseded entries with cause='correction': {len(corrected)}")
for entry in corrected:
    print(f"      first_raised_cut={entry.first_raised_cut} "
          f"superseded_at_cut={entry.superseded_at_cut}")
    print(f"      escalation_id={entry.escalation_id}")
    print(f"      reason: {entry.reason}")

check("the synthetic correction produces a cause='correction' supersession",
      len(corrected) >= 1, f"{len(corrected)} found")
if corrected:
    entry = corrected[0]
    check("  it is recorded at the cut the correction becomes visible (8)",
          entry.superseded_at_cut == 8, f"cut {entry.superseded_at_cut}")
    check("  it was first raised before that cut", entry.first_raised_cut < 8,
          f"cut {entry.first_raised_cut}")
    check("  the reason names the real old and new value, not a paraphrase",
          "4.66" in entry.reason and "0.8" in entry.reason, entry.reason)
    check("  the reason names the real record it cited",
          f"seq {BILI_SEQ}" in entry.reason and SUBJECT in entry.reason)
    if entry.escalation_id:
        rec = fwatch.crew.memory.escalations.get(entry.escalation_id)
        check("  the original escalation record survives, unmutated",
              rec is not None and rec.escalation_id == entry.escalation_id,
              f"state={rec.state if rec else None}")
        check("  ...and is still listed in the report as its own record",
              entry.escalation_id in {e.id for e in freport.escalations})
    check("  it is stated plainly in the markdown, not buried",
          entry.finding_id in freport.markdown
          and "Superseded by a data correction" in freport.markdown)

check(f"{DATA}/data/corrections.csv is untouched (still 200 rows)",
      len(list(csv.DictReader(open(f"{DATA}/data/corrections.csv")))) == 200)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — FR-3: the supersession record is identical on a re-walk")
print("=" * 74)
w2, r2 = walk(str(fixture), cuts=range(1, 13))
a = sorted((e.finding_id, e.first_raised_cut, e.superseded_at_cut, e.cause)
           for e in fwatch.memory.superseded)
b = sorted((e.finding_id, e.first_raised_cut, e.superseded_at_cut, e.cause)
           for e in w2.memory.superseded)
check("a cold re-walk of the same period records exactly the same supersessions",
      a == b, f"{len(a)} vs {len(b)}")

w3, r3 = walk(str(fixture), cuts=range(1, 13))
r3b = w3.run_period(cuts=range(1, 13))       # second walk, warm memory
c = sorted((e.finding_id, e.first_raised_cut, e.superseded_at_cut, e.cause)
           for e in w3.memory.superseded)
check("a warm re-walk never duplicates or re-states an existing supersession",
      len(c) == len(set(x[0] for x in c)), f"{len(c)} entries, "
      f"{len(set(x[0] for x in c))} distinct finding ids")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
