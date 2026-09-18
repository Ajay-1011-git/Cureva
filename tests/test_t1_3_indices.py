"""T1.3 VERIFY — StudyGraph construction and indices against the real data."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stage1.atlas import StudyGraph, ALL_DOMAINS, PRO_DOMAIN, site_of

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data")

print("=== VERIFY: real record counts per domain ===")
raw = {}
for d in ("DM","AE","LB","VS","EX","CM","DS","MH","EG"):
    raw[d] = len(list(csv.DictReader(open(f"hackathon-data/data/{d}.csv", newline=""))))
for d in ALL_DOMAINS:
    n = len(g.by_domain[d])
    src = raw.get(d, 0)
    print(f"  {d:4} indexed={n:>6}   csv rows={src:>6}")
    check(f"{d} indexed count == csv rows", n == src)
check("len(by_domain['LB']) == 14400", len(g.by_domain["LB"]) == 14400, f"got {len(g.by_domain['LB'])}")
check("len(by_domain['DM']) == 241", len(g.by_domain["DM"]) == 241, f"got {len(g.by_domain['DM'])}")
check("0 malformed rows skipped", g.malformed_rows == 0)

print("\n=== VERIFY: PRO slot reserved and empty ===")
check("PRO in by_domain", PRO_DOMAIN in g.by_domain)
check("PRO is empty", g.by_domain[PRO_DOMAIN] == [])
check("PRO in ALL_DOMAINS", PRO_DOMAIN in ALL_DOMAINS)

print("\n=== VERIFY: subject/domain and key indices ===")
r = g.by_key[("LB", "042-S07-001", 25)]
print(f"  by_key[('LB','042-S07-001',25)] -> {r['LBTESTCD']}={r['LBORRES']} {r['LBORRESU']} {r['VISIT']}")
check("by_key finds the worked-example ALT row", r["LBTESTCD"] == "ALT" and r["LBORRES"] == "3.995")
lb = g.by_usubjid_domain[("042-S07-001", "LB")]
check("by_usubjid_domain returns that subject's LB rows", len(lb) == 60, f"got {len(lb)}")
check("derived _site is correct", r["_site"] == "S07")
check("derived _seq is int", r["_seq"] == 25 and isinstance(r["_seq"], int))
check("derived _cut is int", r["_cut"] == 5)
check("site_of is study-prefix agnostic (not hard-coded to '042')",
      site_of("999-S03-001") == "S03" and site_of("ABC-X9-1") == "X9" and site_of("nope") is None)
check("SITEID is authoritative and agrees with the id shape for all 241 subjects",
      all(g.site_by_subject[r["USUBJID"]] == site_of(r["USUBJID"]) for r in g.by_domain["DM"])
      and len(g.site_by_subject) == 241)
check("site_for prefers DM.SITEID", g.site_for("042-S07-001") == "S07")

print("\n=== VERIFY: reference_ranges pre-index ===")
for k, v in sorted(g.reference_ranges.items()):
    print(f"  {k} -> {v}")
check("8 range rows indexed", len(g.reference_ranges) == 8)
check("('ALT','CENTRAL') -> U/L 7-56", g.reference_ranges[("ALT","CENTRAL")] == ("U/L", 7.0, 56.0))
check("('ALT','S07') -> ukat/L", g.reference_ranges[("ALT","S07")][0] == "ukat/L")

print("\n=== VERIFY: corrections index + value_at_cut (correction direction) ===")
cor = list(csv.DictReader(open("hackathon-data/data/corrections.csv", newline="")))
c = cor[0]
key = ("LB", c["usubjid"], int(c["seq"]), "LBORRES")
print(f"  correction: {c['usubjid']} #{c['seq']} {c['old_value']} -> {c['new_value']} at cut {c['cut']}")
print(f"  index[{key}] = {g.corrections_index[key]}")
rec = g.by_key[("LB", c["usubjid"], int(c["seq"]))]
print(f"  raw CSV value: {rec['LBORRES']!r}  (cut_available={rec['_cut']}, corrected_at={rec['_corrected_at']})")
for cut in (1, 4, 5, 12, None):
    v = g.value_at_cut("LB", c["usubjid"], int(c["seq"]), "LBORRES", rec["LBORRES"], cut)
    want = c["old_value"] if (cut is not None and cut < int(c["cut"])) else c["new_value"]
    print(f"    value_at_cut(cut={str(cut):>4}) = {v!r}   expect {want!r}")
    check(f"value at cut={cut}", v == want)
check("all 200 corrections indexed", len(g.corrections_index) == 200)
check("every correction history sorted ascending",
      all(h == sorted(h) for h in g.corrections_index.values()))

print("\n=== VERIFY: cut -> protocol version, from real cuts.csv ===")
for cut in list(range(1, 13)) + [None, 0, 99]:
    print(f"    protocol_version_at({str(cut):>4}) = {g.protocol_version_at(cut)}")
check("cuts 1-4 -> v1", all(g.protocol_version_at(c) == 1 for c in (1,2,3,4)))
check("cuts 5-8 -> v2", all(g.protocol_version_at(c) == 2 for c in (5,6,7,8)))
check("cuts 9-12 -> v3", all(g.protocol_version_at(c) == 3 for c in (9,10,11,12)))
check("cut=None -> latest (3)", g.protocol_version_at(None) == 3)
name, _ = g.protocol_document_at(None)
check("protocol_document_at(None) -> protocol_v3", name == "protocol_v3", f"got {name}")
name, _ = g.protocol_document_at(1)
check("protocol_document_at(1) -> protocol_v1", name == "protocol_v1", f"got {name}")

print("\n=== VERIFY: document re-read on change (FR-5) ===")
import pathlib, time as _t
p = pathlib.Path("hackathon-data/documents/protocol_v1.md")
original = p.read_text()
first = g.document("protocol_v1")
try:
    p.write_text(original + "\n<!-- edited by T1.3 test -->\n")
    _t.sleep(0.01)
    second = g.document("protocol_v1")
    check("changed file is re-read, not served from cache", second != first and "T1.3 test" in second)
finally:
    p.write_text(original)
third = g.document("protocol_v1")
check("restored file is re-read again", third == original)
check("document_names lists real docs", set(g.document_names()) ==
      {"lab-manual","lab-manual_v3","protocol_v1","protocol_v2","protocol_v3","sap"},
      str(g.document_names()))

print("\n=== VERIFY: records() cut filtering matches study.py's own loader ===")
for cut in (1, 3, 5, 12, None):
    mine = len(g.records("LB", cut=cut))
    theirs = len(g.study.records("LB", cut=cut))
    print(f"    cut={str(cut):>4}: StudyGraph={mine:>6}  study.Study={theirs:>6}")
    check(f"LB cut={cut} agrees with study.Study", mine == theirs)
mine = len(g.records("LB", site="S07"))
theirs = len(g.study.records("LB", site="S07"))
check("site filter agrees with study.Study on this study", mine == theirs, f"{mine} vs {theirs}")

print("\n=== VERIFY: construction is repeatable ===")
g2 = StudyGraph("hackathon-data")
check("second construction gives identical counts",
      {d: len(g2.by_domain[d]) for d in ALL_DOMAINS} == {d: len(g.by_domain[d]) for d in ALL_DOMAINS})

print("\n" + ("ALL T1.3 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
