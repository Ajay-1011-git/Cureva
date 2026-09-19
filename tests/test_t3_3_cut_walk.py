"""T3.3 VERIFY — the period walk is cheap, and it is genuinely self-correcting.

Two assertions, per the task:

(a) **Performance.** A 12-cut walk must not re-parse a CSV per cut. Stage 1's
    `StudyGraph.build(cut=N)` re-filters already-loaded indices, and that single
    fact is what makes twelve cuts affordable. This is *instrumented*, not
    argued from timing: `csv.DictReader` is counted, so "no CSV is re-parsed"
    is a measured zero rather than an inference from a fast clock. Real timings
    are printed alongside it.

(b) **Correctness.** A finding whose underlying value changes must be absent
    from the later cut's fresh DETECT sweep. The real practice data and a
    clearly-marked synthetic correction are both exercised, because the real
    corrections turn out not to flip anything (see the honest result printed
    below) and a requirement this load-bearing should not rest on a case the
    data does not actually contain.

Run: .venv/bin/python tests/test_t3_3_cut_walk.py
"""
import csv
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Question
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
SNAPSHOT_CODES = [
    "HYS_LAW_CANDIDATE", "SAE_MISCODED", "LAB_UNIT_MISMATCH", "DUPLICATE_SUBJECT",
    "VISIT_OUT_OF_WINDOW", "AE_BEFORE_FIRST_DOSE", "MISSING_EXPOSURE_RECORD",
    "INCLUSION_VIOLATION", "EXCLUSION_VIOLATION", "PROHIBITED_CONMED", "DOSING_ERROR",
]

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def sweep(graph: StudyGraph, atlas: Atlas, cut: int) -> dict:
    """The same fresh DETECT sweep `run_cycle` performs, at one cut."""
    graph.build(cut)
    out = {}
    for code in SNAPSHOT_CODES:
        answer = atlas.answer(Question(id=f"q{cut}-{code}", kind="finding", text="",
                                       params={"code": code}, cut=cut))
        for finding in answer.findings:
            out[finding.fingerprint()] = finding
    return out


# ==========================================================================
print("=" * 74)
print("(a) PERFORMANCE — twelve cuts must not re-parse a CSV twelve times")
print("=" * 74)

parses = {"n": 0}
real_reader = csv.DictReader


class CountingDictReader(real_reader):           # type: ignore[misc,valid-type]
    def __init__(self, *args, **kwargs):
        parses["n"] += 1
        super().__init__(*args, **kwargs)


csv.DictReader = CountingDictReader              # type: ignore[assignment]
try:
    t0 = time.perf_counter()
    graph = StudyGraph(DATA)
    atlas = Atlas(graph)
    construct_s = time.perf_counter() - t0
    parses_after_construction = parses["n"]

    state = Path(tempfile.mkdtemp(prefix="cureva-t33-"))
    crew = ReviewCrew(DATA, atlas, state_dir=state)
    parses_after_crew = parses["n"]

    # 12 bare re-filters, for the comparison the task asks for
    t0 = time.perf_counter()
    for cut in range(1, 13):
        graph.build(cut)
    twelve_builds_s = time.perf_counter() - t0
    parses_after_builds = parses["n"]

    watch = StudyWatch(DATA, crew)
    t0 = time.perf_counter()
    watch.run_period(cuts=range(1, 13))
    walk_s = time.perf_counter() - t0
    parses_after_walk = parses["n"]
finally:
    csv.DictReader = real_reader                 # type: ignore[assignment]

print(f"  CSV parses during StudyGraph+Atlas construction : {parses_after_construction}")
print(f"  CSV parses during ReviewCrew construction       : "
      f"{parses_after_crew - parses_after_construction}  (its own Study, for escalate/query_site)")
print(f"  CSV parses during 12x graph.build(cut=N)        : "
      f"{parses_after_builds - parses_after_crew}")
print(f"  CSV parses during the full 12-cut run_period()  : "
      f"{parses_after_walk - parses_after_builds}")
print()
print(f"  construction                 : {construct_s:6.2f}s")
print(f"  12x build(cut=N) alone       : {twelve_builds_s:6.2f}s")
print(f"  full 12-cut run_period()     : {walk_s:6.2f}s")
print(f"  run_period overhead per cut  : {(walk_s - twelve_builds_s) / 12:6.3f}s")

check("no CSV is parsed by 12x build(cut=N) — it re-filters loaded indices",
      parses_after_builds - parses_after_crew == 0,
      f"{parses_after_builds - parses_after_crew} parse(s)")
check("no CSV is parsed by the full 12-cut run_period()",
      parses_after_walk - parses_after_builds == 0,
      f"{parses_after_walk - parses_after_builds} parse(s)")
check("the 12-cut walk stays well inside the harness time budget (120s)",
      walk_s < 120, f"{walk_s:.2f}s")

# ==========================================================================
print()
print("=" * 74)
print("(b) CORRECTNESS — a finding whose underlying value changes goes away")
print("=" * 74)

print("\n  -- the REAL practice data, reported honestly --")
corrections = list(csv.DictReader(open(f"{DATA}/data/corrections.csv")))
cuts_seen = {c["cut"] for c in corrections}
domains_seen = {c["domain"] for c in corrections}
deltas = sorted(abs(float(c["new_value"]) - float(c["old_value"])) / abs(float(c["old_value"]))
                for c in corrections if c["old_value"] and float(c["old_value"]))
print(f"  corrections.csv: {len(corrections)} rows, all at cut {cuts_seen}, all domain {domains_seen}")
print(f"  relative change: min={deltas[0]:.4f} median={deltas[len(deltas)//2]:.4f} "
      f"max={deltas[-1]:.4f}  (reason: {corrections[0]['reason']!r})")

g2 = StudyGraph(DATA)
a2 = Atlas(g2)
before, after = sweep(g2, a2, 4), sweep(g2, a2, 5)
vanished = set(before) - set(after)
print(f"\n  findings at cut 4: {len(before)}   at cut 5: {len(after)}")
print(f"  present at cut 4, absent at cut 5: {len(vanished)}")
for fp in sorted(vanished):
    print(f"      {fp}")

corrected_records = {("LB", c["usubjid"], int(c["seq"])) for c in corrections}
citing = [fp for fp, f in before.items()
          if any((e.domain, e.usubjid, e.seq) in corrected_records for e in f.evidence)]
print(f"\n  cut-4 findings citing a record corrected at cut 5: {len(citing)}")
for fp in citing:
    print(f"      {before[fp].code:<24} {before[fp].usubjid}  still present at cut 5: {fp in after}")

check("HONEST RESULT: no real correction flips a real finding "
      "(all 200 are <=3.5% 'central lab re-issue')",
      all(fp in after for fp in citing), f"{len(citing)} finding(s) checked")

# The one real disappearance, and why it is not a correction at all.
real_case = [fp for fp in vanished if fp.startswith("MISSING_EXPOSURE_RECORD")]
if real_case:
    subject = before[real_case[0]].usubjid
    ex_rows = [r for r in g2.study.domains["EX"] if r["USUBJID"] == subject]
    first_ex_cut = min(int(r.get("cut_available") or 1) for r in ex_rows)
    print(f"\n  the one real disappearance is {real_case[0]}")
    print(f"      {subject}'s first EX record has cut_available={first_ex_cut}")
    check("REAL self-correcting case: the finding goes away because the missing "
          "record arrived, not because a value was corrected",
          first_ex_cut == 5, f"first EX visible at cut {first_ex_cut}")

print("\n  -- SYNTHETIC corrections (clearly marked; the real ones flip nothing) --")


def fixture_with(rows: list[str]) -> Path:
    """A private copy of the study with extra corrections appended.

    `hackathon-data/` itself is never written to — the real file is re-counted
    at the end of this test to prove it.
    """
    root = Path(tempfile.mkdtemp(prefix="cureva-t33-fixture-")) / "synthetic-study"
    shutil.copytree(DATA, root)
    with (root / "data" / "corrections.csv").open("a", newline="") as fh:
        for row in rows:
            fh.write(row + "\n")
    return root


def hys_subjects(root: Path, cut: int) -> set[str]:
    graph = StudyGraph(str(root))
    answer = Atlas(graph).answer(Question(id=f"hys{cut}", kind="finding", text="",
                                          params={"code": "HYS_LAW_CANDIDATE"}, cut=cut))
    return {f.usubjid for f in answer.findings}


# 042-S05-003's HYS_LAW_CANDIDATE first appears at cut 6. Hy's law needs a
# transaminase AND bilirubin, so there are two different corrections to try and
# they do NOT behave the same. Both are exercised, because the difference is
# the detector being right rather than a quirk.
SUBJECT = "042-S05-003"
NOTE = "SYNTHETIC test correction (T3.3) - not organiser data"

print("\n  case 1: correct ALT only (LBSEQ 31, 238.9 -> 52.0 at cut 8)")
alt_only = fixture_with([f"8,LB,{SUBJECT},31,LBORRES,238.9,52.0,{NOTE}"])
for cut in (7, 8):
    print(f"      cut {cut}: {sorted(hys_subjects(alt_only, cut))}")
check("correcting ALT alone does NOT clear the finding — the detector correctly "
      "falls back to AST (144.6 U/L > 3x ULN), which is still elevated",
      SUBJECT in hys_subjects(alt_only, 8))

_g = StudyGraph(str(alt_only))
_rec = _g.by_key.get(("LB", SUBJECT, 31))
check("  ...and the correction itself really did apply (238.9 at cut 7, 52.0 at cut 8)",
      _g.record_value(_rec, "LBORRES", 7) == "238.9"
      and _g.record_value(_rec, "LBORRES", 8) == "52.0",
      f"cut7={_g.record_value(_rec, 'LBORRES', 7)} cut8={_g.record_value(_rec, 'LBORRES', 8)}")

print("\n  case 2: correct the shared bilirubin term (LBSEQ 33, 4.66 -> 0.8 at cut 8)")
print("          Hy's law needs bilirubin on BOTH its ALT and AST branches, so")
print("          this is the one correction that genuinely undoes the finding.")
bili = fixture_with([f"8,LB,{SUBJECT},33,LBORRES,4.66,0.8,{NOTE}"])
for cut in (6, 7, 8, 9, 12):
    marker = "<- correction visible from here" if cut >= 8 else ""
    print(f"      cut {cut:>2}: {sorted(hys_subjects(bili, cut))} {marker}")

check(f"{SUBJECT} IS flagged at cut 7 (before the correction)",
      SUBJECT in hys_subjects(bili, 7))
check(f"{SUBJECT} is ABSENT from cut 8's fresh sweep (correction now visible)",
      SUBJECT not in hys_subjects(bili, 8))
check(f"{SUBJECT} stays absent at cuts 9 and 12",
      SUBJECT not in hys_subjects(bili, 9) and SUBJECT not in hys_subjects(bili, 12))
check("no other subject's finding is disturbed by the correction",
      hys_subjects(bili, 7) - {SUBJECT} <= hys_subjects(bili, 12) - {SUBJECT},
      f"cut7={sorted(hys_subjects(bili, 7) - {SUBJECT})} "
      f"cut12={sorted(hys_subjects(bili, 12) - {SUBJECT})}")
check(f"{DATA}/data/corrections.csv is untouched (still 200 rows)",
      len(list(csv.DictReader(open(f"{DATA}/data/corrections.csv")))) == 200)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
