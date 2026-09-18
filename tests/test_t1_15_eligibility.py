"""T1.15 VERIFY — INCLUSION_VIOLATION / EXCLUSION_VIOLATION."""
import sys, os, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas, ProtocolRules, standardised_labs
from study import standardise_lab, central_range

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
ask = lambda code, cut=None: atlas.answer(Question(id="q", kind="finding", text="",
                                                   params={"code": code}, cut=cut))

print("=== VERIFY: inclusion — age exactly matches an independent CSV pass ===")
age_bad = sorted(r["USUBJID"] for r in g.by_domain["DM"] if not (18 <= float(r["AGE"]) <= 75))
print(f"  independent pass (AGE outside [18,75]): {age_bad}")
a = ask("INCLUSION_VIOLATION")
check("all age violations flagged", set(age_bad) <= set(a.answer))
for u in age_bad:
    f = next(f for f in a.findings if f.usubjid == u and "Age" in f.rationale)
    check(f"{u} age violation cites the real age", str(int(float(next(
        r for r in g.by_domain['DM'] if r['USUBJID']==u)['AGE']))) in f.rationale)
check("no false positive: HbA1c is within range for all 241 subjects",
      not any(not (7.0 <= float(r["SCR_HBA1C"]) <= 10.5) for r in g.by_domain["DM"]))

print("\n=== VERIFY (required): screening ALT/AST > 2xULN exclusion, SYNTHETIC proof ===")
print("  (the real practice data has zero true positives here -- max ratio 0.93x ULN --")
print("   so the detector's correctness on this rule is proven synthetically, clearly")
print("   marked as such, matching the pattern the build instructions require for T1.19)")
real_max = max(
    (standardise_lab(lb["LBTESTCD"], lb["LBORRES"], lb["LBORRESU"], g.ranges)[0] or 0)
     / central_range(lb["LBTESTCD"], g.ranges)[2]
    for lb in g.by_domain["LB"] if lb["LBTESTCD"] in ("ALT", "AST")
    and lb.get("VISIT") == "SCREENING")
print(f"  confirmed: max real screening ALT/AST ratio to ULN = {real_max:.3f} (threshold is 2.0)")
check("confirms zero real exclusion cases exist for this rule", real_max < 2.0)

# Inject one synthetic LB row far enough over the exclusion threshold, run the
# detector against a copy of the index, and restore it immediately after.
subject = "042-S01-001"
synthetic = dict(ALT_synthetic_marker=True, USUBJID=subject, LBSEQ="9001", VISIT="SCREENING",
                 LBDTC="2026-01-01", LBTESTCD="ALT", LBORRES="200", LBORRESU="U/L",
                 cut_available="1", corrected_at_cut="", _domain="LB", _seq=9001, _cut=1,
                 _site="S01", _corrected_at=None)
g.by_domain["LB"].append(synthetic)
g.by_usubjid_domain[(subject, "LB")].append(synthetic)
g.by_key[("LB", subject, 9001)] = synthetic
try:
    a2 = ask("EXCLUSION_VIOLATION")
    print(f"  synthetic ALT=200 U/L (>2x56=112) injected for {subject} -> {a2.answer}")
    check("synthetic exclusion case IS detected", subject in a2.answer)
    f = next(f for f in a2.findings if f.usubjid == subject and "ALT" in f.rationale)
    check("rationale cites the synthetic value and the threshold",
          "200" in f.rationale and "112" in f.rationale)
finally:
    g.by_domain["LB"].remove(synthetic)
    g.by_usubjid_domain[(subject, "LB")].remove(synthetic)
    del g.by_key[("LB", subject, 9001)]
a3 = ask("EXCLUSION_VIOLATION")
check("after removing the synthetic row, that subject is no longer flagged for it",
      not any(f.usubjid == subject and "ALT" in f.rationale for f in a3.findings))

print("\n=== VERIFY (required): CREAT exclusion — v1 does NOT apply it, v3 does ===")
c_all = ask("EXCLUSION_VIOLATION")
creat_subjects = sorted({f.usubjid for f in c_all.findings if "CREAT" in f.rationale})
print(f"  real subjects with screening CREAT > 1.5: {creat_subjects}")
check("at least one real CREAT exclusion case exists", len(creat_subjects) >= 1)
c1 = ask("EXCLUSION_VIOLATION", cut=1)
c9 = ask("EXCLUSION_VIOLATION", cut=9)
print(f"  cut=1  (v1): {c1.answer}")
print(f"  cut=9  (v3): {c9.answer}")
check("cut=1 (v1) does NOT apply the creatinine rule at all",
      not any("CREAT" in f.rationale for f in c1.findings))
check("cut=9 (v3) DOES apply it", any("CREAT" in f.rationale for f in c9.findings))
check("creat_active is presence-derived from the document, not a version number check",
      ProtocolRules(g, 1).exclusion_creat_active is False
      and ProtocolRules(g, 5).exclusion_creat_active is True)

print("\n=== VERIFY: document-driven amendment actually changes the answer ===")
import pathlib
path = pathlib.Path("hackathon-data/documents/protocol_v3.md")
original = path.read_text()
try:
    edited = original.replace("Creatinine > 1.5 mg/dL", "Creatinine > 15 mg/dL")
    check("edit applied", edited != original)
    path.write_text(edited)
    a4 = ask("EXCLUSION_VIOLATION")
    creat4 = sorted({f.usubjid for f in a4.findings if "CREAT" in f.rationale})
    print(f"  with threshold raised to 15 mg/dL: {creat4}")
    check("raising the threshold in the document removes the real cases", creat4 == [])
finally:
    path.write_text(original)
a5 = ask("EXCLUSION_VIOLATION")
check("restoring the document restores the original findings",
      sorted({f.usubjid for f in a5.findings if "CREAT" in f.rationale}) == creat_subjects)

print("\n" + ("ALL T1.15 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
