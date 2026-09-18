"""T1.2 VERIFY — standardise_lab against the real practice data.

Run: .venv/bin/python tests/test_t1_2_standardise.py
"""
import csv, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from study import (Study, standardise_lab, central_range, to_number,
                   UnitMismatch, NoReferenceRange, check_conversion_against_ranges)

s = Study("hackathon-data")
R = s.ranges
LB = s.domains["LB"]
fails = []

def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

def row(usubjid, seq):
    return next(r for r in LB if r["USUBJID"] == usubjid and r["LBSEQ"] == str(seq))

print("=== VERIFY 1: the ukat/L conversion, on a real record ===")
r = row("042-S07-001", 1)
print(f"  real row: {r['USUBJID']} #{r['LBSEQ']} {r['VISIT']} {r['LBTESTCD']}={r['LBORRES']} {r['LBORRESU']}")
got = standardise_lab(r["LBTESTCD"], r["LBORRES"], r["LBORRESU"], R)
print(f"  standardise_lab -> {got}")
check("0.265 ukat/L -> ~15.9 U/L, was_converted=True",
      abs(got[0] - 15.9) < 1e-9 and got[1] == "U/L" and got[2] is True)

print("\n=== VERIFY 2: the organiser's Hy's law worked example, 042-S07-001 WEEK8 ===")
alt = row("042-S07-001", 25); bili = row("042-S07-001", 27)
for lbl, rec in (("ALT", alt), ("BILI", bili)):
    print(f"  real row: #{rec['LBSEQ']} {rec['VISIT']} {rec['LBDTC']} "
          f"{rec['LBTESTCD']}={rec['LBORRES']} {rec['LBORRESU']}")
alt_v, alt_u, alt_c = standardise_lab(alt["LBTESTCD"], alt["LBORRES"], alt["LBORRESU"], R)
bil_v, bil_u, bil_c = standardise_lab(bili["LBTESTCD"], bili["LBORRES"], bili["LBORRESU"], R)
_, _, alt_high = central_range("ALT", R)
_, _, bil_high = central_range("BILI", R)
print(f"  ALT  : {alt['LBORRES']} {alt['LBORRESU']} -> {alt_v} {alt_u} (converted={alt_c})")
print(f"         3 x ULN = 3 x {alt_high} = {3*alt_high}   -> exceeds: {alt_v > 3*alt_high}")
print(f"  BILI : {bili['LBORRES']} {bili['LBORRESU']} -> {bil_v} {bil_u} (converted={bil_c})")
print(f"         2 x ULN = 2 x {bil_high} = {2*bil_high}   -> exceeds: {bil_v > 2*bil_high}")
check("ALT 3.995 ukat/L -> 239.7 U/L", abs(alt_v - 239.7) < 1e-6, f"got {alt_v}")
check("ALT converted flag is True", alt_c is True)
check("ALT 239.7 > 3xULN (168)", alt_v > 3 * alt_high)
check("BILI 5.38 mg/dL needs no conversion", bil_v == 5.38 and bil_c is False)
check("BILI 5.38 > 2xULN (2.4)", bil_v > 2 * bil_high)

print("\n=== the bug this function exists to prevent ===")
raw = to_number(alt["LBORRES"])
print(f"  raw 3.995 compared to central ULN {alt_high} directly -> flagged? {raw > 3*alt_high}")
check("unconverted comparison would MISS this real Hy's law case", not (raw > 3 * alt_high))

print("\n=== VERIFY 3: same-unit path is not 'converted' ===")
r = row("042-S01-001", 1)
got = standardise_lab(r["LBTESTCD"], r["LBORRES"], r["LBORRESU"], R)
check(f"{r['LBTESTCD']} {r['LBORRES']} {r['LBORRESU']} -> {got}",
      got == (40.4, "U/L", False))

print("\n=== VERIFY 4: unusable values survive, unit check still runs ===")
for raw in ("<5", "ND", ""):
    v, u, c = standardise_lab("ALT", raw, "U/L", R)
    check(f"ALT {raw!r} U/L -> (None, 'U/L', False)", (v, u, c) == (None, "U/L", False))
try:
    standardise_lab("ALT", "ND", "mg/dL", R)
    check("bad unit + unusable value still raises UnitMismatch", False)
except UnitMismatch as e:
    check("bad unit + unusable value still raises UnitMismatch", True, f"-> {e}")

print("\n=== VERIFY 5: unknown unit raises UnitMismatch (synthetic row) ===")
for bad_unit in ("mg/dL", "mmol/L", ""):
    try:
        standardise_lab("ALT", "42", bad_unit, R)
        check(f"ALT in {bad_unit!r} raises", False)
    except UnitMismatch as e:
        check(f"ALT in {bad_unit!r} raises UnitMismatch", True, f"-> {e}")
try:
    standardise_lab("NOSUCHTEST", "1", "U/L", R)
    check("unknown test raises NoReferenceRange", False)
except NoReferenceRange as e:
    check("unknown test raises NoReferenceRange (not UnitMismatch)", True, f"-> {e}")
check("NoReferenceRange is NOT a UnitMismatch subclass",
      not issubclass(NoReferenceRange, UnitMismatch))

print("\n=== VERIFY 6: micro-sign variants fold to one unit ===")
for variant in ("ukat/L", "µkat/L", "μkat/L", " UKAT/L "):
    v, _, c = standardise_lab("ALT", "3.995", variant, R)
    check(f"unit {variant!r} -> {v} (converted={c})", abs(v - 239.7) < 1e-6 and c)

print("\n=== VERIFY 7: every real LB row standardises, zero unit mismatches ===")
mismatch, norange, ok = [], [], 0
for r in LB:
    try:
        standardise_lab(r["LBTESTCD"], r["LBORRES"], r["LBORRESU"], R); ok += 1
    except UnitMismatch: mismatch.append(r)
    except NoReferenceRange: norange.append(r)
print(f"  {ok}/{len(LB)} rows standardised | UnitMismatch={len(mismatch)} | NoReferenceRange={len(norange)}")
check("zero false-positive unit mismatches on real data", not mismatch)
check("every real test has a CENTRAL reference range", not norange)

print("\n=== VERIFY 8: conversion table agrees with the local-lab reference rows ===")
w = check_conversion_against_ranges(R)
for r in R:
    if (r["LAB"] or "").upper() != "CENTRAL":
        cu, cl, ch = central_range(r["LBTESTCD"], R)
        lo, _, _ = standardise_lab(r["LBTESTCD"], r["LOW"], r["UNIT"], R)
        hi, _, _ = standardise_lab(r["LBTESTCD"], r["HIGH"], r["UNIT"], R)
        print(f"  {r['LBTESTCD']}@{r['LAB']}: {r['LOW']}-{r['HIGH']} {r['UNIT']} -> "
              f"{lo:.4g}-{hi:.4g} {cu}   CENTRAL says {cl}-{ch}")
check("no conversion-table disagreements", not w, str(w))

print("\n" + ("ALL T1.2 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
