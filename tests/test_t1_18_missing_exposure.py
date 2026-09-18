"""T1.18 VERIFY — MISSING_EXPOSURE_RECORD."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
ask = lambda cut=None: atlas.answer(Question(id="m", kind="finding", text="",
                                             params={"code": "MISSING_EXPOSURE_RECORD"}, cut=cut))

print("=== VERIFY (required): does any real subject have zero EX records? ===")
dm = {r["USUBJID"] for r in g.by_domain["DM"]}
ex = {r["USUBJID"] for r in g.by_domain["EX"]}
zero_ex = sorted(dm - ex)
print(f"  subjects with zero EX records: {zero_ex}")
check("exactly one real subject has zero EX records (042-S05-021)",
      zero_ex == ["042-S05-021"])

a = ask()
print(f"\n  detector -> {a.answer}")
check("the detector finds exactly that subject", a.answer == zero_ex)
f = a.findings[0]
print(f"  rationale: {f.rationale}")
check("rationale states zero EX records plainly", "zero EX" in f.rationale)
check("rationale names the other domain that IS present (MH)", "MH" in f.rationale)
check("confidence reflects an unambiguous absence", f.confidence >= 0.85)

print("\n=== VERIFY (required per build-instructions): partial case has zero real instances,")
print("    stated explicitly, NOT silently treated as untested ===")
partial = [f2 for f2 in a.findings if "EX (dosing) record on or before" in f2.rationale]
print(f"  real partial-missing-exposure findings: {len(partial)}")
check("zero real partial cases -- confirmed, not assumed", partial == [])
import pathlib
det = pathlib.Path("stage1/atlas.py").read_text()
det = det[det.index("def detect_missing_exposure_record"):]
check("this fact is documented in the detector's own docstring, not hidden",
      "zero real instances" in det)

print("\n=== VERIFY: the detector fires on the partial case when it IS true (synthetic) ===")
subject = "042-S01-001"                 # a subject with normal EX coverage
earliest_ex = min(g.record_date(r, None) for r in g.records("EX", cut=None, usubjid=subject))
before_ex = earliest_ex.replace(year=earliest_ex.year - 1)
synth_lb = dict(USUBJID=subject, LBSEQ="9001", VISIT="WEEK99", LBDTC=before_ex.isoformat(),
                LBTESTCD="ALT", LBORRES="40", LBORRESU="U/L", cut_available="1",
                corrected_at_cut="", _domain="LB", _seq=9001, _cut=1, _site="S01",
                _corrected_at=None)
g.by_domain["LB"].append(synth_lb)
g.by_usubjid_domain[(subject, "LB")].append(synth_lb)
g.by_key[("LB", subject, 9001)] = synth_lb
try:
    a2 = ask()
    hit = [f2 for f2 in a2.findings if f2.usubjid == subject]
    print(f"  {subject}'s earliest real EX date: {earliest_ex}")
    print(f"  synthetic LB row dated {before_ex} (one year before it), no EX record precedes it:")
    print(f"     {[h.rationale for h in hit]}")
    check("synthetic post-EX-coverage visit is detected as a gap", len(hit) == 1)
    check("cites WEEK99 by name", hit and "WEEK99" in hit[0].rationale)
finally:
    g.by_domain["LB"].remove(synth_lb)
    g.by_usubjid_domain[(subject, "LB")].remove(synth_lb)
    del g.by_key[("LB", subject, 9001)]
a3 = ask()
check("removing the synthetic row removes the finding",
      not any(f2.usubjid == subject for f2 in a3.findings))

print("\n=== VERIFY: cut scoping — the subject only appears once enrolled ===")
enrolled_cut = next(r["_cut"] for r in g.by_domain["DM"] if r["USUBJID"] == "042-S05-021")
print(f"  042-S05-021 first visible at cut {enrolled_cut}")
before = ask(enrolled_cut - 1) if enrolled_cut > 1 else None
after = ask(enrolled_cut)
check("subject not flagged before their DM row is visible",
      before is None or "042-S05-021" not in before.answer)
check("subject IS flagged once visible", "042-S05-021" in after.answer)

print("\n=== VERIFY: T1.12's zero-EX check and this detector agree ===")
from stage1.atlas import DETECTORS
no_dose_ae = atlas.answer(Question(id="a", kind="finding", text="",
                                   params={"code": "AE_BEFORE_FIRST_DOSE"}))
check("042-S05-021 (no first dose) never appears in AE_BEFORE_FIRST_DOSE",
      "042-S05-021" not in no_dose_ae.answer)

print("\n" + ("ALL T1.18 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
