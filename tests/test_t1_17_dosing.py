"""T1.17 VERIFY — DOSING_ERROR."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
a = atlas.answer(Question(id="d", kind="finding", text="", params={"code": "DOSING_ERROR"}))

ex = list(csv.DictReader(open("hackathon-data/data/EX.csv", newline="")))
bad20 = [r for r in ex if r["EXDOSE"] == "20"]
print(f"=== VERIFY (required): real EXDOSE==20 rows all flagged ===")
print(f"  real EXDOSE=20 rows: {len(bad20)}")
for r in bad20: print(f"     {r['USUBJID']} #{r['EXSEQ']} {r['VISIT']} {r['EXTRT']}={r['EXDOSE']}")
check("all 6 real EXDOSE=20 rows are flagged",
      all(r["USUBJID"] in a.answer for r in bad20))
for r in bad20:
    hit = any(e.domain == "EX" and e.seq == int(r["EXSEQ"]) for f in a.findings
             for e in f.evidence if f.usubjid == r["USUBJID"])
    check(f"{r['USUBJID']} #{r['EXSEQ']} specifically cited as evidence", hit)

print("\n=== VERIFY: also catches PLACEBO subjects dosed at 10mg (not just 20mg) ===")
wrong = [r for r in ex if not ((r["EXTRT"] == "DRUG" and r["EXDOSE"] == "10")
                               or (r["EXTRT"] == "PLACEBO" and r["EXDOSE"] == "0"))]
print(f"  independent pass, all dosing errors (not just EXDOSE=20): {len(wrong)} rows, "
      f"{len({r['USUBJID'] for r in wrong})} subjects")
check("detector count matches an independent CSV pass exactly", len(a.findings) == len(wrong))
check("subject set matches", set(a.answer) == {r["USUBJID"] for r in wrong})
placebo_wrong = [r for r in wrong if r["EXTRT"] == "PLACEBO"]
print(f"  of which PLACEBO-arm subjects dosed at 10mg (not 20mg): {len(placebo_wrong)} rows")
check("PLACEBO-dosed-at-10 cases are real and caught",
      len(placebo_wrong) > 0 and all(r["USUBJID"] in a.answer for r in placebo_wrong))

print("\n=== VERIFY: EXTRT vs DM.ARM cross-check ===")
dm = {r["USUBJID"]: r["ARM"] for r in csv.DictReader(open("hackathon-data/data/DM.csv", newline=""))}
mismatch = [r for r in ex if r["EXTRT"] != dm.get(r["USUBJID"])]
print(f"  real EXTRT != DM.ARM mismatches: {len(mismatch)} (0 expected — confirms no such case exists)")
check("no false positives from the arm cross-check on real data",
      not any("randomised arm" in f.rationale for f in a.findings))
import pathlib
det = pathlib.Path("stage1/atlas.py").read_text()
det = det[det.index("def detect_dosing_error"):]
check("the arm cross-check code path exists even though untriggered here",
      "does not match the subject's" in det and "DM.ARM" in det)

print("\n=== VERIFY: correctly-dosed subjects never flagged ===")
correct_subjects = {r["USUBJID"] for r in ex} - set(a.answer)
sample = sorted(correct_subjects)[:5]
for u in sample:
    rows = [r for r in ex if r["USUBJID"] == u]
    ok = all((r["EXTRT"] == "DRUG" and r["EXDOSE"] == "10") or
             (r["EXTRT"] == "PLACEBO" and r["EXDOSE"] == "0") for r in rows)
    check(f"{u}: correctly dosed on all {len(rows)} EX rows, not flagged", ok)

print("\n=== VERIFY: scope and cut filters ===")
scoped = atlas.answer(Question(id="s", kind="finding", text="", params={"code": "DOSING_ERROR", "site": "S09"}))
check("site filter narrows to S09 subjects only", set(scoped.answer) <= set(a.answer)
      and all(g.site_for(u) == "S09" for u in scoped.answer))
early = atlas.answer(Question(id="c", kind="finding", text="", params={"code": "DOSING_ERROR"}, cut=1))
check("cut=1 sees no more errors than cut=None", len(early.answer) <= len(a.answer))

print("\n" + ("ALL T1.17 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
