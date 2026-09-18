"""T1.5 VERIFY — patient360 against the real data."""
import sys, os, csv, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stage1.atlas import StudyGraph, ALL_DOMAINS

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
SUBJ = "042-S07-001"
p = g.patient360(SUBJ)

print(f"=== VERIFY: patient360({SUBJ!r}) ===")
print(f"  site={p['site']} arm={p['arm']} age={p['age']} sex={p['sex']} country={p['country']}")
print(f"  enrolled={p['enrolled']} first_dose={p['first_dose']} records={p['record_count']} cut={p['cut']}")
print("  per-domain record counts:")
for d in ALL_DOMAINS:
    print(f"     {d:4} {len(p[d]):>4}")

print("\n  the required VERIFY: LB contains LBSEQ==25 with LBTESTCD=='ALT'")
hit = [r for r in p["LB"] if r.get("LBSEQ") == "25"]
print(f"     found: {hit[0] if hit else None}")
check("LB has a record with LBSEQ==25 and LBTESTCD=='ALT'",
      bool(hit) and hit[0]["LBTESTCD"] == "ALT")
check("that record is the worked example (3.995 ukat/L)",
      bool(hit) and hit[0]["LBORRES"] == "3.995" and hit[0]["LBORRESU"] == "ukat/L")

print("\n=== VERIFY: every domain present even when empty ===")
for d in ALL_DOMAINS:
    check(f"{d} key present", d in p and isinstance(p[d], list))
check("PRO present and empty", p["PRO"] == [])
check("domains sub-dict has all ten", set(p["domains"]) == set(ALL_DOMAINS))

print("\n=== VERIFY: a subject with sparse data still gets every domain ===")
dm = {r["USUBJID"] for r in g.by_domain["DM"]}
sparse = min(dm, key=lambda u: g.patient360(u)["record_count"])
sp = g.patient360(sparse)
print(f"  sparsest subject {sparse}: {sp['record_count']} records, "
      f"{ {d: len(sp[d]) for d in ALL_DOMAINS} }")
check("sparse subject still has all ten domain keys", set(sp["domains"]) == set(ALL_DOMAINS))

print("\n=== VERIFY: unknown subject returns empty, does not raise ===")
u = g.patient360("NO-SUCH-SUBJECT")
check("unknown subject -> 0 records, enrolled False",
      u["record_count"] == 0 and u["enrolled"] is False and set(u["domains"]) == set(ALL_DOMAINS))

print("\n=== VERIFY: derived _ fields are not leaked into the rendered rows ===")
leaked = [k for r in p["LB"] for k in r if k.startswith("_") and not k.startswith("_superseded_")]
check("no internal _domain/_seq/_cut/_site keys in output", not leaked, str(set(leaked)))

print("\n=== VERIFY: corrections are reflected at the snapshot cut ===")
cor = list(csv.DictReader(open("hackathon-data/data/corrections.csv", newline="")))
c = next(c for c in cor if c["old_value"] != c["new_value"])
print(f"  correction: {c['usubjid']} #{c['seq']} {c['old_value']} -> {c['new_value']} at cut {c['cut']}")
for cut, want in ((4, c["old_value"]), (5, c["new_value"]), (None, c["new_value"])):
    g.build(cut=cut)
    row = next(r for r in g.patient360(c["usubjid"])["LB"] if r["LBSEQ"] == c["seq"])
    print(f"    cut={str(cut):>4}: LBORRES={row['LBORRES']!r}  superseded={row.get('_superseded_LBORRES')!r}")
    check(f"patient360 shows the value in force at cut {cut}", row["LBORRES"] == want)
g.build(cut=5)
row = next(r for r in g.patient360(c["usubjid"])["LB"] if r["LBSEQ"] == c["seq"])
check("the superseded value stays visible after a correction",
      row.get("_superseded_LBORRES") == c["old_value"])

print("\n=== VERIFY: cut filtering flows through patient360 ===")
g.build(cut=1); n1 = g.patient360(SUBJ)["record_count"]
g.build(cut=12); n12 = g.patient360(SUBJ)["record_count"]
g.build(cut=None); nA = g.patient360(SUBJ)["record_count"]
print(f"  {SUBJ}: cut=1 -> {n1} records, cut=12 -> {n12}, cut=None -> {nA}")
check("record count grows with the cut", n1 < n12 <= nA)

print("\n=== VERIFY: first_dose_date ===")
g.build(cut=None)
fd = g.first_dose_date(SUBJ)
ex = sorted(r["EXSTDTC"] for r in g.records("EX", usubjid=SUBJ))
print(f"  first_dose_date={fd}   earliest EXSTDTC in data={ex[0] if ex else None}")
check("first dose matches the earliest EX record", str(fd) == ex[0])
check("subject with no EX rows -> None", g.first_dose_date("NO-SUCH-SUBJECT") is None)

print("\n=== VERIFY: JSON-serialisable (the demo page has to render it) ===")
try:
    json.dumps(g.patient360(SUBJ), default=str); check("patient360 serialises to JSON", True)
except Exception as e:
    check("patient360 serialises to JSON", False, str(e))

print("\n=== VERIFY: all 241 real subjects render without error ===")
bad = []
for u in sorted(dm):
    try:
        r = g.patient360(u)
        if set(r["domains"]) != set(ALL_DOMAINS): bad.append(u)
    except Exception as e:
        bad.append((u, e))
check("all 241 subjects render", not bad, str(bad[:3]))

print("\n" + ("ALL T1.5 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
