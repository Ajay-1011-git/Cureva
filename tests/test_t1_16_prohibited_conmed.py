"""T1.16 VERIFY — PROHIBITED_CONMED."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas, ProtocolRules

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
ask = lambda cut=None: atlas.answer(Question(id="q", kind="finding", text="",
                                             params={"code": "PROHIBITED_CONMED"}, cut=cut))

cm = list(csv.DictReader(open("hackathon-data/data/CM.csv", newline="")))
gluc = [r for r in cm if r["CMCLAS"] == "SYSTEMIC_GLUCOCORTICOID"]
sulf = [r for r in cm if r["CMCLAS"] == "SULFONYLUREA"]
print(f"real CM.csv: {len(gluc)} SYSTEMIC_GLUCOCORTICOID rows, {len(sulf)} SULFONYLUREA rows")

print("\n=== VERIFY (required): every glucocorticoid row flagged under v1 (prohibited from the start) ===")
a = ask(None)
gluc_flagged = {f.usubjid for f in a.findings if "GLUCOCORTICOID" in f.rationale}
print(f"  flagged: {sorted(gluc_flagged)}")
check("all 8 real Prednisolone/SYSTEMIC_GLUCOCORTICOID rows flagged",
      gluc_flagged == {r["USUBJID"] for r in gluc}, str(gluc_flagged))
check("every real CMTRT is Prednisolone", all(r["CMTRT"] == "Prednisolone" for r in gluc))
check("even the earliest-cut glucocorticoid row (v1) is flagged",
      min(int(r["cut_available"]) for r in gluc) < 5 and
      any(f.usubjid == min(gluc, key=lambda r: int(r["cut_available"]))["USUBJID"]
          for f in a.findings if "GLUCOCORTICOID" in f.rationale))

print("\n=== VERIFY (required): sulfonylurea only flagged under v3 ===")
sulf_flagged = {(f.usubjid, r["cut_available"]) for f in a.findings if "SULFONYLUREA" in f.rationale
               for r in sulf if r["USUBJID"] == f.usubjid}
v3_sulf = {r["USUBJID"] for r in sulf if g.protocol_version_at(int(r["cut_available"])) == 3}
v1v2_sulf = {r["USUBJID"] for r in sulf if g.protocol_version_at(int(r["cut_available"])) < 3}
print(f"  sulfonylurea rows landing under v1/v2 (cut<9): {sorted(v1v2_sulf)} -- must NOT be flagged")
print(f"  sulfonylurea rows landing under v3 (cut>=9):   {sorted(v3_sulf)} -- must be flagged")
flagged_subjects = {f.usubjid for f in a.findings if "SULFONYLUREA" in f.rationale}
check("v3-cut sulfonylurea row(s) flagged", v3_sulf <= flagged_subjects, str(flagged_subjects))
check("v1/v2-cut sulfonylurea rows NOT flagged (prohibited list did not include them yet)",
      not (v1v2_sulf & flagged_subjects), str(v1v2_sulf & flagged_subjects))
check("Glibenclamide is the real CMTRT for sulfonylurea rows",
      all(r["CMTRT"] == "Glibenclamide" for r in sulf))

print("\n=== VERIFY: matched on CMCLAS, not CMTRT ===")
import pathlib
det_src = pathlib.Path("stage1/atlas.py").read_text()
det = det_src[det_src.index("def detect_prohibited_conmed"):]
check("detector reads CMCLAS", '"CMCLAS"' in det)
match_logic = det[:det.index("subject = r.get")]
check("the MATCH logic (not the display text) checks only CMCLAS",
      'CMCLAS' in match_logic and 'record_value(r, "CMTRT"' not in match_logic)

print("\n=== VERIFY: cut scoping across the amendment boundary ===")
for cut in (1, 8, 9, 10, None):
    a2 = ask(cut)
    sulf_count = sum(1 for f in a2.findings if "SULFONYLUREA" in f.rationale)
    print(f"  cut={str(cut):>4} -> {len(a2.answer)} subjects total, {sulf_count} sulfonylurea")
check("cut=8 (v2) has zero sulfonylurea findings",
      sum(1 for f in ask(8).findings if "SULFONYLUREA" in f.rationale) == 0)
real_cut = int(next(r for r in sulf if r["USUBJID"] == "042-S08-013")["cut_available"])
print(f"  the one qualifying sulfonylurea row has cut_available={real_cut} (first visible then, not at cut 9 itself)")
check(f"it IS flagged once its own cut ({real_cut}) is reached",
      sum(1 for f in ask(real_cut).findings if "SULFONYLUREA" in f.rationale) == 1)
check(f"it is NOT flagged one cut earlier ({real_cut - 1}, not yet visible)",
      sum(1 for f in ask(real_cut - 1).findings if "SULFONYLUREA" in f.rationale) == 0)

print("\n=== VERIFY: prohibited-class list is parsed from the document ===")
r1 = ProtocolRules(g, 1); r3 = ProtocolRules(g, 9)
print(f"  v1: {sorted(r1.prohibited_conmed_classes)}")
print(f"  v3: {sorted(r3.prohibited_conmed_classes)}")
check("v1 has exactly SYSTEMIC_GLUCOCORTICOID", r1.prohibited_conmed_classes == frozenset({"SYSTEMIC_GLUCOCORTICOID"}))
check("v3 adds SULFONYLUREA on top", r3.prohibited_conmed_classes == frozenset({"SYSTEMIC_GLUCOCORTICOID", "SULFONYLUREA"}))

print("\n=== VERIFY: no unaffected class is ever flagged ===")
other_classes = {"ACE_INHIBITOR", "PPI", "ANTIDIABETIC", "ANALGESIC", "STATIN", "CCB", "ANTIPLATELET", "NSAID"}
check("no finding cites a non-prohibited class",
      not any(any(c in f.rationale for c in other_classes) for f in a.findings))

print("\n" + ("ALL T1.16 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
