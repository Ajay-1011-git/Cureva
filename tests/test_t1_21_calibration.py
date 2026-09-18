"""T1.21 VERIFY — confidence calibration pass across every detector.

Lists each detector's observed confidence range on the real practice study and
the justification for it, then checks the one real incentive the harness's own
scoring formula creates: penalty = 0.5 * confidence^2, applied ONLY when
correct==0. So confidence must never be inflated on a shaky detection, and an
honest empty answer with clean logic should be high-confidence, not low.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas, DETECTORS

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)

JUSTIFICATION = {
    "HYS_LAW_CANDIDATE": (0.62, 0.92,
        "0.92 for a clean pair with wide margins over both thresholds; drops to "
        "0.62 when either the enzyme or bilirubin value sits within 5% of its "
        "threshold (genuine measurement-noise territory). Skipped below-detection "
        "or unit-mismatched values elsewhere for the SAME subject do NOT lower "
        "confidence in a pair that already qualifies on its own two records -- a "
        "skipped value can only hide a finding, never invent one."),
    "SAE_MISCODED": (0.95, 0.95,
        "Two explicit coded flags (AESHOSP, AESER) directly contradicting each "
        "other on one record. No interpretation, no missing data possible."),
    "AE_BEFORE_FIRST_DOSE": (0.60, 0.90,
        "0.90 when the AE precedes first dose by >=2 days; drops to 0.60 for a "
        "1-day gap, where a date transcription slip is as plausible as a real "
        "ordering error. All 8 real cases have a >=2-day gap; the <2-day path "
        "exists in code and is exercised by synthetic construction only."),
    "DUPLICATE_SUBJECT": (0.55, 0.92,
        "A heuristic match (this schema has no cross-subject person id) starts "
        "at 0.55 for the 3 key fields alone and rises 0.09 per additional "
        "independently-agreeing field (ARM, RFSTDTC, SCR_HBA1C, AGE), capped at "
        "0.92 -- never certain, since coincidence can never be ruled out from "
        "demographics alone; explicitly never 1.0."),
    "VISIT_OUT_OF_WINDOW": (0.68, 0.90,
        "0.90 when a visit misses its window by 2+ days beyond the boundary; "
        "0.68 for a miss of exactly 1 day past the window, where a date entry "
        "slip is as likely as a real deviation."),
    "INCLUSION_VIOLATION": (0.95, 0.95,
        "A recorded demographic (AGE, SCR_HBA1C) compared directly to a "
        "documented numeric range. No measurement noise, no missing-data path."),
    "EXCLUSION_VIOLATION": (0.90, 0.90,
        "A standardised lab value (through the same standardise_lab as Hy's "
        "law) compared to a documented threshold. Held slightly below the "
        "inclusion checks' 0.95 because it depends on unit conversion having "
        "gone correctly, one more step than a raw demographic comparison."),
    "PROHIBITED_CONMED": (0.92, 0.92,
        "A coded class (CMCLAS) matched directly against a documented "
        "prohibited-class list resolved per the record's own cut."),
    "DOSING_ERROR": (0.90, 0.95,
        "0.95 for a dose that does not match the protocol's 10mg/0mg rule "
        "(exact numeric comparison); 0.90 for the rarer EXTRT-vs-DM.ARM cross-"
        "check, held slightly lower since it implies the more severe claim "
        "that the wrong treatment was dispensed, not just the wrong amount."),
    "MISSING_EXPOSURE_RECORD": (0.80, 0.90,
        "0.90 for the primary, unambiguous case (an enrolled subject with zero "
        "EX records at all); 0.80 for the partial visit-without-prior-EX case, "
        "which depends on every domain's dates having parsed and could be a "
        "recording-order artifact rather than a true gap."),
    "LAB_UNIT_MISMATCH": (0.90, 0.90,
        "The unit either matches a known reference row/conversion or it does "
        "not -- a boolean fact once standardise_lab has run, no judgement call."),
}

print("=== per-detector confidence range, observed on the real practice study ===\n")
for code in sorted(DETECTORS):
    ans = atlas.answer(Question(id="q", kind="finding", text="", params={"code": code}))
    confs = [f.confidence for f in ans.findings]
    if confs:
        lo, hi = min(confs), max(confs)
        print(f"  {code:24} n={len(confs):>3}  observed [{lo:.2f}, {hi:.2f}]")
    else:
        lo = hi = ans.confidence
        print(f"  {code:24} n=  0  (honest empty)  confidence={ans.confidence:.2f}")
    print(f"    -> {JUSTIFICATION[code][2]}")
    exp_lo, exp_hi = JUSTIFICATION[code][0], JUSTIFICATION[code][1]
    check(f"{code}: observed range is within the documented justification",
          lo >= exp_lo - 0.01 and hi <= exp_hi + 0.01,
          f"observed=[{lo},{hi}] documented=[{exp_lo},{exp_hi}]")

print("\n=== every detector is registered ===")
check("all 11 Stage-1 detectors are registered", len(DETECTORS) == 11, str(sorted(DETECTORS)))
check("every documented detector matches an actually-registered one",
      set(JUSTIFICATION) == set(DETECTORS))

print("\n=== the one real incentive: never inflate confidence on a shaky detection ===")
print("  harness formula: penalty = 0.5 * confidence^2, applied only when correct==0")
print("  so confidence should track genuine signal quality, and a low-margin case")
print("  should never claim the same confidence as a clean one\n")
hys = atlas.answer(Question(id="h", kind="finding", text="", params={"code": "HYS_LAW_CANDIDATE"}))
for f in hys.findings:
    print(f"  {f.usubjid}: confidence={f.confidence}  (all 3 real cases have wide margins, so all 0.92)")
check("no HYS_LAW_CANDIDATE finding is inflated to 1.0 or above 0.92",
      all(f.confidence <= 0.92 for f in hys.findings))

print("\n=== honest empty answers are high-confidence, not treated as uncertain ===")
empties = []
for code in sorted(DETECTORS):
    ans = atlas.answer(Question(id="q", kind="finding", text="",
                                params={"code": code, "site": "S99"}))  # no such site
    if ans.answer == []:
        empties.append((code, ans.confidence))
print(f"  {len(empties)} detectors queried against a non-existent site (S99), all honest empties:")
for code, conf in empties:
    print(f"    {code:24} confidence={conf}")
check("every honest empty-scope answer keeps confidence >= 0.9",
      all(conf >= 0.9 for _, conf in empties), str(empties))

print("\n=== an unknown code (we did not look) is NEVER confident ===")
unknown = atlas.answer(Question(id="u", kind="finding", text="", params={"code": "NOT_REAL"}))
check("unknown-code answer has confidence 0, distinct from a real empty answer",
      unknown.confidence == 0.0)

print("\n" + ("ALL T1.21 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
