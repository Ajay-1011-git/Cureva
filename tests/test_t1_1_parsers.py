"""T1.1 VERIFY — parse_date / to_number against the real practice data.

Run: .venv/bin/python tests/test_t1_1_parsers.py
"""
import csv, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from study import parse_date, to_number

D = "hackathon-data/data/"
fails = []

def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label:38} -> {got!r}   (want {want!r})")

print("=== spec cases from build-instructions T1.1 ===")
check('parse_date("2026-01-08")', parse_date("2026-01-08"), date(2026, 1, 8))
check('parse_date("03-FEB-2026")', parse_date("03-FEB-2026"), date(2026, 2, 3))
check('to_number("<5")',  to_number("<5"),  None)
check('to_number("ND")',  to_number("ND"),  None)
check('to_number("0,32")', to_number("0,32"), 0.32)
check('to_number("")',    to_number(""),    None)
check('to_number("40.4")', to_number("40.4"), 40.4)
check('parse_date("")',   parse_date(""),   None)
check('parse_date(None)', parse_date(None), None)

print("\n=== unrecognised format must RAISE, not return None ===")
for bad in ("08/01/2026", "2026-1-8", "Jan 8 2026", "20260108"):
    try:
        parse_date(bad); print(f"  FAIL  {bad!r} returned silently"); fails.append(f"raise {bad}")
    except ValueError as e:
        print(f"  PASS  {bad!r:14} -> ValueError: {e}")

print("\n=== every date value in every date column of the real study parses ===")
datecols = [("DM.csv","BRTHDTC"),("DM.csv","RFSTDTC"),("AE.csv","AESTDTC"),("AE.csv","AEENDTC"),
            ("LB.csv","LBDTC"),("VS.csv","VSDTC"),("EX.csv","EXSTDTC"),("CM.csv","CMSTDTC"),
            ("DS.csv","DSSTDTC"),("EG.csv","EGDTC")]
total = 0
for f, c in datecols:
    rows = list(csv.DictReader(open(D + f, newline="")))
    bad = []
    for r in rows:
        try: parse_date(r[c])
        except ValueError as e: bad.append((r["USUBJID"], r[c]))
    total += len(rows)
    print(f"  {'PASS' if not bad else 'FAIL'}  {f:8} {c:8} {len(rows):>6} values, {len(bad)} unparsable {bad[:2]}")
    if bad: fails.append(f"{f}:{c}")
print(f"  -> {total} date values parsed with zero failures")

print("\n=== real LBORRES values, one live example of each shape ===")
rows = list(csv.DictReader(open(D + "LB.csv", newline="")))
seen = {}
for r in rows:
    v = r["LBORRES"]
    if v == "": t = "empty"
    elif v.startswith("<"): t = "below-detection"
    elif v.upper() == "ND": t = "not-done"
    elif "," in v: t = "decimal-comma"
    else: t = "plain"
    seen.setdefault(t, r)
for t, r in seen.items():
    raw = r["LBORRES"]; got = to_number(raw)
    want = None if t in ("empty", "below-detection", "not-done") else float(raw.replace(",", "."))
    check(f'{t:16} {r["USUBJID"]} #{r["LBSEQ"]} {raw!r}', got, want)

print("\n=== below-detection is None, never 0.0 (the whole point) ===")
check('to_number("<5") is not 0.0', to_number("<5") == 0.0, False)

print("\n" + ("ALL T1.1 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
