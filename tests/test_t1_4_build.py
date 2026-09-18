"""T1.4 VERIFY — StudyGraph.build(cut) against the real data."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stage1.atlas import StudyGraph, ALL_DOMAINS

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data")

print("=== VERIFY: build(cut=None) ===")
full = g.build(cut=None)
print(f"  {full}")
check("returns exactly the 5 graded keys",
      set(full) == {"nodes","edges","subjects","cut","ms"}, str(sorted(full)))
check("subjects == 241", full["subjects"] == 241, f"got {full['subjects']}")
check("cut is None", full["cut"] is None)
check("ms is an int", isinstance(full["ms"], int))
total_csv = sum(len(list(csv.DictReader(open(f"hackathon-data/data/{d}.csv", newline=""))))
                for d in ("DM","AE","LB","VS","EX","CM","DS","MH","EG"))
print(f"  total rows across the 9 CSVs: {total_csv}")
check("nodes == every record in the study", full["nodes"] == total_csv, f"got {full['nodes']}")
check("edges == nodes (every record's subject is enrolled)", full["edges"] == full["nodes"])
print(f"  per-domain: {g.stats['per_domain']}")

print("\n=== VERIFY: later cuts reveal more records ===")
prev = None
rows = []
for cut in range(1, 13):
    st = g.build(cut=cut)
    rows.append(st)
    print(f"  cut={cut:>2}  nodes={st['nodes']:>6}  subjects={st['subjects']:>4}  "
          f"protocol=v{g.stats['protocol_version']}  corrections_applied={g.stats['corrections_applied']:>3}  {st['ms']}ms")
    if prev is not None:
        check(f"cut {cut} has >= cut {cut-1} nodes", st["nodes"] >= prev["nodes"])
    prev = st
check("build(cut=1) nodes < build(cut=12) nodes", rows[0]["nodes"] < rows[11]["nodes"],
      f"{rows[0]['nodes']} < {rows[11]['nodes']}")

print("\n=== VERIFY: nodes at cut N == cuts.csv new_records cumulative ===")
cuts = list(csv.DictReader(open("hackathon-data/data/cuts.csv", newline="")))
running = 0
ok = True
for c, st in zip(cuts, rows):
    running += int(c["new_records"])
    match = running == st["nodes"]
    ok &= match
    print(f"  cut={c['cut']:>2}  cuts.csv cumulative={running:>6}  build nodes={st['nodes']:>6}  {'match' if match else 'MISMATCH'}")
check("build nodes track cuts.csv new_records cumulatively", ok)
print(f"  cumulative through cut 12 = {running}; full study = {full['nodes']} "
      f"(difference {full['nodes']-running} = records never released in a cut)")

print("\n=== VERIFY: corrections are actually applied at the snapshot cut ===")
cor = list(csv.DictReader(open("hackathon-data/data/corrections.csv", newline="")))
c = cor[0]
rec = g.by_key[("LB", c["usubjid"], int(c["seq"]))]
for cut in (4, 5, None):
    g.build(cut=cut)
    v = g.record_value(rec, "LBORRES")
    want = c["old_value"] if cut == 4 else c["new_value"]
    print(f"  after build(cut={cut}): record_value(LBORRES) = {v!r}  expect {want!r}")
    check(f"corrected value follows the snapshot cut ({cut})", v == want)

print("\n=== VERIFY: idempotent ===")
a = g.build(cut=6); b = g.build(cut=6)
check("same cut twice -> identical stats (ms aside)",
      {k: v for k, v in a.items() if k != "ms"} == {k: v for k, v in b.items() if k != "ms"},
      f"{a} vs {b}")
g.build(cut=None); c1 = g.stats["per_domain"]
g.build(cut=3); g.build(cut=None); c2 = g.stats["per_domain"]
check("re-building after another cut restores the same view", c1 == c2)

print("\n=== VERIFY: performance (TNFR-2 target: under 5s) ===")
import time as _t
t0 = _t.perf_counter(); st = g.build(cut=None); wall = _t.perf_counter() - t0
print(f"  full build: reported {st['ms']}ms, measured {wall*1000:.0f}ms")
check("full build well under the 5s target", wall < 5.0)
t0 = _t.perf_counter()
for cut in range(1, 13): g.build(cut=cut)
print(f"  all 12 cuts sequentially: {(_t.perf_counter()-t0)*1000:.0f}ms")

print("\n=== VERIFY: PRO is counted but empty ===")
g.build(cut=None)
check("PRO contributes 0 nodes", g.stats["per_domain"]["PRO"] == 0)
check("PRO still in the per-domain breakdown", "PRO" in g.stats["per_domain"])

print("\n" + ("ALL T1.4 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
