"""T3.8 VERIFY — `IMPLAUSIBLE_SITE_PATTERN`, a stated design choice.

This detector was not specified upstream, so the rule is stated in full in
`stage3/detectors.py` before it is implemented, and measured here.

The practice data turns out to contain a genuine positive that no build
document mentions: site S11 joins at cut 6 and its glucose values barely move
at all — 0.5% of the spread every other site shows on the same test. That is
the target, and it is real, not synthetic.

The load-bearing check is PART 3. The rule requires a site to be flat BOTH
within a cut and across cuts, and this test proves that second condition is not
decoration: on this very data, an across-cut-only rule reports a clean site as
fabricated.

Run: .venv/bin/python tests/test_t3_8_implausible_site.py
"""
import csv
import logging
import os
import re
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3 import detectors
from stage3.watch import StudyWatch
from study import to_number

logging.basicConfig(level=logging.CRITICAL)

REPO = Path(__file__).resolve().parent.parent
DATA = "hackathon-data"
CODE = "IMPLAUSIBLE_SITE_PATTERN"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def walk(data_dir: str, cuts=range(1, 13)):
    state = Path(tempfile.mkdtemp(prefix="cureva-t38-"))
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state)
    watch = StudyWatch(data_dir, crew)
    return watch, watch.run_period(cuts=cuts)


# ==========================================================================
print("=" * 74)
print("PART 1 — the REAL result on the practice data")
print("=" * 74)
watch, report = walk(DATA)
hits = [f for f in report.signals if f.code == CODE]
print(f"\n  {CODE} findings across the real 12-cut period: {len(hits)}")
for f in hits:
    print(f"\n  site={f.site} severity={f.severity} confidence={f.confidence}")
    print(f"  rationale: {f.rationale}")
    print(f"  evidence : {[(e.domain, e.usubjid, e.seq) for e in f.evidence]}")

check("exactly one site is flagged on the whole practice study", len(hits) == 1,
      f"{len(hits)}")
if hits:
    f = hits[0]
    check("  it is S11 — the real flat-data site found in the T3.0 audit",
          f.site == "S11", f.site or "")
    check("  it names the measurement", "GLUC" in f.rationale)
    check("  it quotes BOTH spreads as a percentage of this study's own",
          "% of the typical spread" in f.rationale
          and "% of the typical movement" in f.rationale)
    check("  it says plainly that the comparison is relative, not a fixed number",
          "relative to this study's own spread, not to a fixed threshold" in f.rationale)
    check("  it says this is a data-integrity signal, not a clinical finding",
          "not a clinical finding about any subject" in f.rationale)

    graph = StudyGraph(DATA)
    graph.build(12)
    print("\n  the cited records, read back from the real CSV:")
    values = []
    for ref in f.evidence:
        rec = graph.by_key.get((ref.domain, ref.usubjid, ref.seq))
        print(f"      {ref.domain} {ref.usubjid} seq {ref.seq}: "
              f"{rec.get('LBTESTCD')} {rec.get('LBORRES')} {rec.get('LBORRESU')} "
              f"(cut_available={rec.get('cut_available')})")
        values.append(to_number(rec["LBORRES"]))
    check("  every cited record exists and is a glucose record at S11",
          all(graph.by_key.get((r.domain, r.usubjid, r.seq)) for r in f.evidence))
    spread = (max(values) - min(values)) / statistics.mean(values)
    print(f"      -> those four values span {spread:.2%} of their own mean")
    check("  the uniformity is visible in the cited values themselves",
          spread < 0.05, f"{spread:.2%}")

per_cut = {r.cut: [x for x in r.findings if x.code == CODE] for r in watch.reports}
fired = sorted(c for c, v in per_cut.items() if v)
print(f"\n  fired at cuts: {fired}")
check("it does not fire before it has enough history (S11 joins at cut 6)",
      min(fired) >= 6, f"first fired at cut {min(fired)}")
esc = [e for e in report.escalations if e.code == CODE]
check("  it raises ONE escalation, not one per cut, despite firing repeatedly",
      len(esc) == 1, f"{len(esc)} escalation(s) from {len(fired)} firing cuts")

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the per-site score (KRI.implausibility)")
print("=" * 74)
scores = detectors.site_implausibility(watch.memory, 12)
ranked = sorted(scores.items(), key=lambda kv: -kv[1])
for site, score in ranked:
    print(f"      {site}: {score:.4f}")
check("S11 scores highest", ranked[0][0] == "S11", ranked[0][0])
check("  and is separated from the next site by a wide margin",
      ranked[0][1] > 4 * ranked[1][1],
      f"{ranked[0][1]:.4f} vs {ranked[1][1]:.4f}")
check("  every score is a real fraction in 0..1",
      all(0.0 <= s <= 1.0 for s in scores.values()))

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — why BOTH conditions are required (the load-bearing check)")
print("=" * 74)
uniformity = detectors.site_uniformity(watch.memory, 12)
across_only = sorted(((v["across_ratio"], site, test)
                      for (site, test), v in uniformity.items()))
print("  lowest ACROSS-cut ratios (per-cut median movement vs peers):")
for ratio, site, test in across_only[:4]:
    both = uniformity[(site, test)]
    verdict = ("FLAGGED" if both["within_ratio"] < detectors.UNIFORMITY_RATIO
               else "rejected by the within-cut test")
    print(f"      {site}/{test}: across={ratio:.4f}  within={both['within_ratio']:.4f} "
          f" -> {verdict}")

would_flag = [(s, t) for r, s, t in across_only if r < detectors.UNIFORMITY_RATIO]
actually = [(f.site, "GLUC") for f in hits]
print(f"\n  an across-cut-ONLY rule would flag {len(would_flag)} site/test pair(s): "
      f"{would_flag}")
print(f"  the implemented both-conditions rule flags {len(actually)}: {actually}")
check("across-cut-only would produce a FALSE POSITIVE on this very data",
      len(would_flag) > len(actually),
      f"{len(would_flag)} vs {len(actually)}")
false_positive = [p for p in would_flag if p not in
                  {(f.site, "GLUC") for f in hits}]
if false_positive:
    site, test = false_positive[0]
    stats = uniformity[(site, test)]
    print(f"      the false positive is {site}/{test}: only {stats['cuts']} cuts of "
          f"history, so its per-cut medians look stable by chance — but its "
          f"within-cut spread is {stats['within_ratio']:.2f}x its peers, i.e. normal")
    check("  ...and the within-cut test correctly rejects it",
          stats["within_ratio"] >= detectors.UNIFORMITY_RATIO,
          f"within_ratio={stats['within_ratio']:.4f}")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — GENERALISATION: a different site and a different test")
print("=" * 74)
fixture = Path(tempfile.mkdtemp(prefix="cureva-t38-fixture-")) / "synthetic-study"
shutil.copytree(REPO / DATA, fixture)
TARGET_SITE, TARGET_TEST, FLAT_VALUE = "S06", "HBA1C", 7.10
lb = fixture / "data" / "LB.csv"
rows = list(csv.DictReader(lb.open()))
fields = list(rows[0].keys())
n = 0
for row in rows:
    if row["USUBJID"].split("-")[1] == TARGET_SITE and row["LBTESTCD"] == TARGET_TEST:
        row["LBORRES"] = f"{FLAT_VALUE + (n % 3) * 0.01:.2f}"   # near-constant
        n += 1
with lb.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
print(f"  SYNTHETIC: flattened {n} {TARGET_SITE}/{TARGET_TEST} values to ~{FLAT_VALUE}")
print(f"  (temp copy only; {DATA}/ untouched)")

fwatch, freport = walk(str(fixture))
fhits = [f for f in freport.signals if f.code == CODE]
print(f"\n  findings in the synthetic study: "
      f"{sorted((f.site, f.rationale.split()[1]) for f in fhits)}")
check(f"the planted {TARGET_SITE}/{TARGET_TEST} flat site is detected",
      any(f.site == TARGET_SITE for f in fhits))
planted = next((f for f in fhits if f.site == TARGET_SITE), None)
if planted:
    check(f"  it names {TARGET_TEST}, not GLUC",
          TARGET_TEST in planted.rationale and "GLUC" not in planted.rationale)
check("  the real S11 case is still detected in the same run",
      any(f.site == "S11" for f in fhits))
check(f"  {DATA}/data/LB.csv is untouched",
      len(list(csv.DictReader(open(f"{DATA}/data/LB.csv")))) == 14400)

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — no practice-data value appears in a conditional")
print("=" * 74)
src = (REPO / "stage3" / "detectors.py").read_text()
code_only = re.sub(r'"""(?:.|\n)*?"""', "", src)
code_only = "\n".join(line.split("#")[0] for line in code_only.splitlines())
for needle in ('"S11"', "'S11'", '"GLUC"', "'GLUC'", "0.0050", "0.024"):
    check(f"{needle:<8} never appears in executable code", needle not in code_only)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
