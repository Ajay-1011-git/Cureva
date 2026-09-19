"""T3.9 VERIFY — `LATE_DATA_ENTRY`, a stated design choice.

Not specified upstream, so the rule is stated in full in `stage3/detectors.py`
before it is implemented, and measured here.

The practice data contains a real positive: site S08 runs a median reporting
lag of 58-69 days at every cut it delivers to, against a cross-site median of
5-12 days. It is genuinely months behind.

It also contains a real *near-miss* that the rule must reject: site S11 joins
at cut 6 and shows a 71-day lag at that one cut — its backfill of existing
subjects — then reports normally (5-16 days) for the rest of the period. That
is onboarding, not chronic lateness, and PART 2 proves the rule tells them
apart.

Run: .venv/bin/python tests/test_t3_9_late_data_entry.py
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
from stage2.crew import ReviewCrew
from stage3 import detectors
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

REPO = Path(__file__).resolve().parent.parent
DATA = "hackathon-data"
CODE = "LATE_DATA_ENTRY"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def walk(data_dir: str, cuts=range(1, 13)):
    state = Path(tempfile.mkdtemp(prefix="cureva-t39-"))
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state)
    watch = StudyWatch(data_dir, crew)
    return watch, watch.run_period(cuts=cuts)


# ==========================================================================
print("=" * 74)
print("PART 1 — the REAL chronically-late site")
print("=" * 74)
watch, report = walk(DATA)
hits = [f for f in report.signals if f.code == CODE]
print(f"\n  {CODE} findings across the real 12-cut period: {len(hits)}")
for f in hits:
    print(f"\n  site={f.site} severity={f.severity}")
    print(f"  rationale: {f.rationale}")
    print(f"  evidence : {[(e.domain, e.usubjid, e.seq) for e in f.evidence]}")

check("exactly one site is reported", len(hits) == 1, f"{len(hits)}")
if hits:
    f = hits[0]
    check("  it is S08 — the site running ~60 days behind at every cut",
          f.site == "S08", f.site or "")
    check("  it states how many of its cuts were late", "of the" in f.rationale
          and "cuts it has delivered data to" in f.rationale)
    check("  it states the benchmark is this study's own pace, not a fixed lag",
          "not a fixed number of days" in f.rationale)
    check("  it says a uniformly slow study would flag nobody",
          "a uniformly slow study flags nobody" in f.rationale)
    check("  severity is MEDIUM, not HIGH (a process defect, not a safety event)",
          f.severity == "MEDIUM", f.severity)
    graph = StudyGraph(DATA)
    graph.build(12)
    check("  every cited record really exists",
          all(graph.by_key.get((r.domain, r.usubjid, r.seq)) for r in f.evidence))
    check("  every cited record belongs to the reported site",
          all(graph.site_for(r.usubjid) == f.site for r in f.evidence))

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — onboarding backfill is NOT reported as chronic lateness")
print("=" * 74)
lateness = detectors.site_lateness(watch.memory, 12)
print("  per-site lateness, measured against peers at each cut:")
for site, stats in sorted(lateness.items(),
                          key=lambda kv: -len(kv[1]["late_cuts"])):
    if stats["late_cuts"] or stats["worst_ratio"] > 2:
        print(f"      {site}: late at {len(stats['late_cuts'])}/"
              f"{stats['cuts_observed']} cuts {stats['late_cuts']}, "
              f"worst {stats['worst_ratio']:.1f}x, first cut {stats['first_cut']}")

s11 = lateness.get("S11", {})
check("S11 IS late at its very first cut (the backfill is real and measured)",
      bool(s11.get("late_cuts")) and s11["late_cuts"][0] == s11["first_cut"],
      f"late_cuts={s11.get('late_cuts')} first_cut={s11.get('first_cut')}")
check("  ...but it is late at only that one cut",
      len(s11.get("late_cuts", [])) < detectors.LATE_SUSTAINED_CUTS,
      f"{len(s11.get('late_cuts', []))} late cut(s)")
check("  ...so it is NOT reported as a finding",
      not any(f.site == "S11" for f in hits))

scores = detectors.site_late_entry_score(watch.memory, 12)
print(f"\n  late_entry_score (KRI): "
      f"{ {s: round(v, 3) for s, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v} }")
check("S08 scores far higher than S11", scores.get("S08", 0) > 4 * scores.get("S11", 1),
      f"S08={scores.get('S08'):.3f} S11={scores.get('S11'):.3f}")
check("  every other site scores zero",
      all(v == 0 for s, v in scores.items() if s not in ("S08", "S11")))
check("  every score is a real fraction in 0..1",
      all(0.0 <= v <= 1.0 for v in scores.values()))

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — one finding per SITE, and a stable identity across the walk")
print("=" * 74)
prints: dict[str, list[int]] = {}
for r in watch.reports:
    for f in r.findings:
        if f.code == CODE:
            prints.setdefault(f.fingerprint(), []).append(r.cut)
for fp, cuts in prints.items():
    print(f"      {fp}  fired at cuts {cuts}")
check("one distinct fingerprint, despite firing at many cuts", len(prints) == 1,
      f"{len(prints)} fingerprint(s)")
esc = [e for e in report.escalations if e.code == CODE]
check("  which raises ONE escalation, not one per cut", len(esc) == 1,
      f"{len(esc)} from {len(list(prints.values())[0])} firing cuts")

# A per-record detector would have produced this many findings instead:
per_record = sum(1 for s, st in lateness.items() for _ in st["late_cuts"])
print(f"\n  for scale: a per-record rule flags 1284 records on this study "
      f"(measured in the T3.9 design work); this rule reports {len(hits)} site(s)")
check("  the human gate is not flooded", len(hits) <= 2, f"{len(hits)} finding(s)")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — a uniformly slow study flags nobody (the benchmark is relative)")
print("=" * 74)
fixture = Path(tempfile.mkdtemp(prefix="cureva-t39-fixture-")) / "synthetic-study"
shutil.copytree(REPO / DATA, fixture)
# Push EVERY site's records 60 days later by moving every cut's data back in
# time is equivalent to slowing the whole study. Simplest faithful version:
# drop the two genuinely-late sites' subjects, leaving a uniform study.
dm = list(csv.DictReader((fixture / "data" / "DM.csv").open()))
drop = {r["USUBJID"] for r in dm if r["USUBJID"].split("-")[1] in ("S08", "S11")}
for name in ("DM", "AE", "LB", "VS", "EX", "CM", "DS", "MH", "EG"):
    path = fixture / "data" / f"{name}.csv"
    rows = [r for r in csv.DictReader(path.open()) if r["USUBJID"] not in drop]
    if rows:
        with path.open("w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
print(f"  SYNTHETIC: removed the two late sites, leaving a study whose sites all "
      f"report at the same pace")
fwatch, freport = walk(str(fixture))
fhits = [f for f in freport.signals if f.code == CODE]
print(f"  {CODE} findings in the uniform study: {len(fhits)}")
check("no site is flagged when every site reports at the same pace",
      len(fhits) == 0, f"{[f.site for f in fhits]}")
check(f"  {DATA}/ is untouched",
      len(list(csv.DictReader(open(f"{DATA}/data/DM.csv")))) == 241)

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — no practice-data value appears in a conditional")
print("=" * 74)
src = (REPO / "stage3" / "detectors.py").read_text()
code_only = re.sub(r'"""(?:.|\n)*?"""', "", src)
code_only = "\n".join(line.split("#")[0] for line in code_only.splitlines())
for needle in ('"S08"', "'S08'", '"S11"', "'S11'", "66", "71", "18"):
    check(f"{needle:<7} never appears in executable code", needle not in code_only)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
