"""T1.19 VERIFY — LAB_UNIT_MISMATCH, incl. required synthetic bad-unit proof."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
ask = lambda: atlas.answer(Question(id="u", kind="finding", text="", params={"code": "LAB_UNIT_MISMATCH"}))

print("=== VERIFY (required): zero false positives on real data ===")
a = ask()
print(f"  {a.answer}  (14400 real LB rows scanned)")
check("zero real unit mismatches (every real unit matches a known reference row)",
      a.answer == [] and a.confidence >= 0.9)

print("\n=== VERIFY (required): the detector actually fires on an injected bad-unit row ===")
print("  (clearly marked as synthetic, never mixed into real logic — per the build")
print("   instructions' own required approach for this task)")
subject = "042-S01-001"
synth = dict(USUBJID=subject, LBSEQ="9001", VISIT="SCREENING", LBDTC="2026-01-01",
            LBTESTCD="ALT", LBORRES="42", LBORRESU="mmol/L",   # SYNTHETIC — not a real ALT unit
            cut_available="1", corrected_at_cut="",
            _domain="LB", _seq=9001, _cut=1, _site="S01", _corrected_at=None)
g.by_domain["LB"].append(synth)
g.by_usubjid_domain[(subject, "LB")].append(synth)
g.by_key[("LB", subject, 9001)] = synth
try:
    a2 = ask()
    print(f"  injected SYNTHETIC row: {subject} ALT=42 'mmol/L' (not a real ALT unit anywhere)")
    print(f"  detector -> {a2.answer}")
    check("synthetic bad-unit row IS detected", subject in a2.answer)
    f = next(f for f in a2.findings if f.usubjid == subject)
    print(f"  rationale: {f.rationale}")
    check("rationale names the offending unit", "mmol/L" in f.rationale)
    check("rationale names the test", "ALT" in f.rationale)
    check("evidence cites the synthetic record", any(e.seq == 9001 for e in f.evidence))
finally:
    g.by_domain["LB"].remove(synth)
    g.by_usubjid_domain[(subject, "LB")].remove(synth)
    del g.by_key[("LB", subject, 9001)]

a3 = ask()
check("removing the synthetic row restores zero mismatches", a3.answer == [])

print("\n=== VERIFY: a test absent from reference_ranges.csv is NOT reported as a mismatch ===")
subject2 = "042-S02-001"
synth2 = dict(USUBJID=subject2, LBSEQ="9002", VISIT="SCREENING", LBDTC="2026-01-01",
             LBTESTCD="TOTALPROTEIN", LBORRES="7", LBORRESU="g/dL",  # not in reference_ranges.csv at all
             cut_available="1", corrected_at_cut="",
             _domain="LB", _seq=9002, _cut=1, _site="S02", _corrected_at=None)
g.by_domain["LB"].append(synth2)
g.by_usubjid_domain[(subject2, "LB")].append(synth2)
g.by_key[("LB", subject2, 9002)] = synth2
try:
    a4 = ask()
    check("an un-ranged test is NOT reported as LAB_UNIT_MISMATCH (that's NoReferenceRange, "
          "a different problem)", subject2 not in a4.answer)
finally:
    g.by_domain["LB"].remove(synth2)
    g.by_usubjid_domain[(subject2, "LB")].remove(synth2)
    del g.by_key[("LB", subject2, 9002)]

print("\n=== VERIFY: distinct from the S07 KNOWN local-lab variant (not a mismatch) ===")
s07 = next(r for r in g.by_domain["LB"] if r["USUBJID"] == "042-S07-001" and r["LBORRESU"] == "ukat/L")
print(f"  042-S07-001 real ALT row: {s07['LBORRES']} {s07['LBORRESU']} — a KNOWN local-lab unit,")
print(f"  present in reference_ranges.csv's S07 row, so standardise_lab converts it cleanly")
check("the S07 local-lab unit is NOT reported as a mismatch",
      "042-S07-001" not in a.answer)

print("\n=== VERIFY: cut and scope filters ===")
scoped = atlas.answer(Question(id="s", kind="finding", text="",
                               params={"code": "LAB_UNIT_MISMATCH", "site": "S07"}))
check("site-scoped query on real data is still an honest empty", scoped.answer == [])

print("\n" + ("ALL T1.19 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
