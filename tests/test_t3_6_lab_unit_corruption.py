"""T3.6 VERIFY — `LAB_UNIT_CORRUPTION` on the real S04 glucose case.

Three things are proved, and the third is the one that decides whether this
survives contact with a hidden study:

1. It fires on the real, confirmed S04 case, at the right cut, citing the real
   before/after LB records.
2. It fires on nothing else in the whole practice study — a detector that flags
   every site is not a detector.
3. It fires on a *different* site, a *different* test and a *different*
   conversion factor in a synthetic study. S04 and GLUC are VERIFY targets, not
   branches, and this is what demonstrates that mechanically rather than by
   reading the source and taking its word for it.

Run: .venv/bin/python tests/test_t3_6_lab_unit_corruption.py
"""
import csv
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from study import to_number
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

REPO = Path(__file__).resolve().parent.parent
DATA = "hackathon-data"
CODE = "LAB_UNIT_CORRUPTION"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def walk(data_dir: str, cuts=range(1, 13)):
    state = Path(tempfile.mkdtemp(prefix="cureva-t36-"))
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state)
    watch = StudyWatch(data_dir, crew)
    return watch, watch.run_period(cuts=cuts)


# ==========================================================================
print("=" * 74)
print("PART 1 — the REAL S04 glucose case")
print("=" * 74)
watch, report = walk(DATA)
hits = [f for f in report.signals if f.code == CODE]
print(f"\n  {CODE} findings across the real 12-cut period: {len(hits)}")
for f in hits:
    print(f"\n  site={f.site} severity={f.severity} confidence={f.confidence}")
    print(f"  rationale: {f.rationale}")
    print(f"  evidence : {[(e.domain, e.usubjid, e.seq) for e in f.evidence]}")

check("exactly one finding on the whole practice study", len(hits) == 1, f"{len(hits)}")
if hits:
    f = hits[0]
    check("  it is the real S04 site", f.site == "S04", f.site or "")
    check("  it names glucose", "GLUC" in f.rationale)
    check("  it identifies the cut-7 -> cut-8 transition",
          "cut 7" in f.rationale and "cut 8" in f.rationale)
    check("  it states the measured factor (~16.6), not the textbook one",
          "16.6" in f.rationale)
    check("  it names the real conversion factor it matched (18)",
          "factor of 18" in f.rationale)
    check("  it states that the unit label did NOT change",
          "still reports the unit as 'mg/dL'" in f.rationale)
    check("  severity is HIGH", f.severity == "HIGH")

    print("\n  the cited records, read back from the real CSV:")
    graph = StudyGraph(DATA)
    graph.build(12)
    ok = True
    for ref in f.evidence:
        rec = graph.by_key.get((ref.domain, ref.usubjid, ref.seq))
        if rec is None:
            ok = False
            print(f"      {ref.domain} {ref.usubjid} seq {ref.seq}: MISSING")
            continue
        print(f"      {ref.domain} {ref.usubjid} seq {ref.seq}: "
              f"{rec.get('LBTESTCD')} {rec.get('LBORRES')} {rec.get('LBORRESU')} "
              f"(cut_available={rec.get('cut_available')})")
    check("  every cited record really exists in LB.csv", ok)
    cited = [graph.by_key.get((r.domain, r.usubjid, r.seq)) for r in f.evidence]
    check("  every cited record is a glucose record at site S04",
          all(c and c.get("LBTESTCD") == "GLUC"
              and c["USUBJID"].split("-")[1] == "S04" for c in cited))
    before = [c for c in cited if int(c.get("cut_available") or 1) == 7]
    after = [c for c in cited if int(c.get("cut_available") or 1) == 8]
    check("  the evidence spans BOTH sides of the shift (cut 7 and cut 8)",
          len(before) >= 1 and len(after) >= 1,
          f"{len(before)} before, {len(after)} after")
    # to_number, not float(): the real data mixes plain floats with European
    # decimal commas ("177,7"), which is precisely why study.to_number exists.
    check("  every before value is larger than every after value, as claimed",
          min(to_number(c["LBORRES"]) for c in before)
          > max(to_number(c["LBORRES"]) for c in after),
          f"before={[c['LBORRES'] for c in before]} after={[c['LBORRES'] for c in after]}")

print("\n  it reached the pipeline as a real finding, not a side channel:")
esc = [e for e in report.escalations if e.code == CODE]
check("  an escalation was raised for it", len(esc) == 1, f"{len(esc)}")
if esc:
    print(f"      {esc[0].id}: decision={esc[0].decision!r} site={esc[0].site}")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — it fires on nothing else in the practice study")
print("=" * 74)
series_count = sum(len(h.series) for h in watch.memory.trend_history.values())
sites = len(watch.memory.trend_history)
print(f"  Watch tracked {series_count} (site, test, unit) series across {sites} sites")
check(f"only 1 of {series_count} tracked series was flagged — no false positives",
      len(hits) == 1, f"{len(hits)} flagged")

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — GENERALISATION: a different site, test and factor")
print("=" * 74)
fixture = Path(tempfile.mkdtemp(prefix="cureva-t36-fixture-")) / "synthetic-study"
shutil.copytree(DATA, fixture)

# Pick a site and test that are NOT the practice study's planted case, and a
# conversion factor that is NOT glucose's. CREAT is reported in mg/dL and
# study.py's table carries mg/dL -> umol/L at 88.4, so multiplying a site's
# creatinine by 88.4 from a chosen cut onward is a different mislabel of the
# same shape. Nothing about S04, GLUC or 18 is involved.
TARGET_SITE, TARGET_TEST, TARGET_FACTOR, FROM_CUT = "S02", "CREAT", 88.4, 10
lb_path = fixture / "data" / "LB.csv"
rows = list(csv.DictReader(lb_path.open()))
fieldnames = list(rows[0].keys())
changed = 0
for row in rows:
    if (row["USUBJID"].split("-")[1] == TARGET_SITE
            and row["LBTESTCD"] == TARGET_TEST
            and int(row.get("cut_available") or 1) >= FROM_CUT):
        value = to_number(row["LBORRES"])
        if value is not None:
            row["LBORRES"] = f"{value * TARGET_FACTOR:.2f}"
            changed += 1
with lb_path.open("w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"  SYNTHETIC: multiplied {changed} {TARGET_SITE}/{TARGET_TEST} values by "
      f"{TARGET_FACTOR} from cut {FROM_CUT} (unit label left as-is)")
print(f"  (written to a temp copy; {DATA}/ is never modified)")

fwatch, freport = walk(str(fixture))
fhits = [f for f in freport.signals if f.code == CODE]
print(f"\n  {CODE} findings in the synthetic study: {len(fhits)}")
for f in fhits:
    print(f"      site={f.site}: {f.rationale[:150]}...")

synthetic = [f for f in fhits if f.site == TARGET_SITE]
check(f"the planted {TARGET_SITE}/{TARGET_TEST} x{TARGET_FACTOR} shift is detected",
      len(synthetic) == 1, f"{len(synthetic)} found")
if synthetic:
    f = synthetic[0]
    check(f"  it names {TARGET_TEST}, not GLUC", TARGET_TEST in f.rationale
          and "GLUC" not in f.rationale)
    check(f"  it identifies the cut-{FROM_CUT} transition",
          f"cut {FROM_CUT}" in f.rationale, f.rationale[:120])
    check(f"  it matched the {TARGET_FACTOR} conversion factor, not 18",
          "88.4" in f.rationale and "factor of 18 " not in f.rationale)
check("  the real S04 case is still detected in the same run (both coexist)",
      any(f.site == "S04" for f in fhits))
check(f"  {DATA}/data/LB.csv is untouched",
      len(list(csv.DictReader(open(f"{DATA}/data/LB.csv")))) == 14400)

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — no practice-data value appears in a conditional")
print("=" * 74)
src = (REPO / "stage3" / "detectors.py").read_text()
# Strip docstrings and comments: naming the real case in prose is required by
# the task, using it in a branch is forbidden.
code_only = re.sub(r'"""(?:.|\n)*?"""', "", src)
code_only = "\n".join(line.split("#")[0] for line in code_only.splitlines())
for needle in ('"S04"', "'S04'", '"GLUC"', "'GLUC'", "18.0", "16.6", '"S11"', "'S11'"):
    check(f"{needle:<8} never appears in executable code", needle not in code_only)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
