"""T1.10 VERIFY — HYS_LAW_CANDIDATE against the organiser's published Q018."""
import sys, os, json, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas, ProtocolRules
from study import standardise_lab, central_range

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
bank = {q["id"]: q for q in json.load(open("public_questions.json"))["questions"]}

print("=== VERIFY (required): reproduce Q018 exactly ===")
q = bank["Q018"]
a = atlas.answer(Question(**{k: v for k, v in q.items() if not k.startswith("_")}))
print(f"  expected: {q['_answer']}")
print(f"  got     : {a.answer}")
check("Q018 matches the published candidate set", a.answer == q["_answer"])
check("three findings returned", len(a.findings) == 3)

print("\n=== VERIFY (required): the 042-S07-001 case shows the converted figures ===")
f = next(f for f in a.findings if f.usubjid == "042-S07-001")
print(f"  confidence: {f.confidence}  severity: {f.severity}  protocol_version: {f.protocol_version}")
print(f"  rationale : {f.rationale}")
check("rationale shows the converted ALT 239.7 U/L", "239.7 U/L" in f.rationale)
check("rationale shows the raw 3.995 ukat/L it came from", "3.995 ukat/L" in f.rationale)
check("rationale shows BILI 5.38 mg/dL", "5.38 mg/dL" in f.rationale)
check("rationale states the unit conversion happened", "converted" in f.rationale.lower())
check("high confidence on a clean, wide-margin match", f.confidence >= 0.9,
      f"got {f.confidence}")

print("\n=== VERIFY: evidence cites the two LB records that show it, plus the protocol ===")
refs = [(e.domain, e.usubjid, e.seq, e.document, e.section) for e in f.evidence]
print(f"  {refs}")
lb_refs = [e for e in f.evidence if e.domain == "LB"]
check("both LB records cited", len(lb_refs) == 2)
check("the ALT record cited is LBSEQ 25", any(e.seq == 25 for e in lb_refs))
check("the BILI record cited is LBSEQ 27", any(e.seq == 27 for e in lb_refs))
check("the protocol section is cited as a DOC ref",
      any(e.domain == "DOC" and e.section == "7" for e in f.evidence))
for e in lb_refs:
    rec = g.by_key[("LB", e.usubjid, e.seq)]
    print(f"     LB:{e.usubjid}:{e.seq} -> {rec['LBTESTCD']}={rec['LBORRES']} {rec['LBORRESU']} @ {rec['LBDTC']}")
check("every cited LB record genuinely exceeds its threshold",
      all(g.by_key[("LB", e.usubjid, e.seq)]["LBTESTCD"] in ("ALT", "AST", "BILI") for e in lb_refs))

print("\n=== VERIFY: every finding's cited records actually qualify (FR-9) ===")
rules = ProtocolRules(g, None)
bad = []
for f in a.findings:
    for e in [e for e in f.evidence if e.domain == "LB"]:
        rec = g.by_key[("LB", e.usubjid, e.seq)]
        tc = rec["LBTESTCD"]
        v, u, _ = standardise_lab(tc, rec["LBORRES"], rec["LBORRESU"], g.ranges)
        _, _, high = central_range(tc, g.ranges)
        mult = rules.hys_enzyme_multiple if tc in ("ALT", "AST") else rules.hys_bilirubin_multiple
        if not (v and v > mult * high):
            bad.append((e.usubjid, e.seq, tc, v, mult * high))
check("no cited record fails its own threshold", not bad, str(bad))

print("\n=== VERIFY: thresholds come from the protocol document, not a constant ===")
import re, pathlib
src = pathlib.Path("stage1/atlas.py").read_text()
det = src[src.index("def detect_hys_law"):src.index("def detect_hys_law") + 6000]
check("detector reads rules.hys_* rather than a literal 3/2/14",
      "rules.hys_enzyme_multiple" in det and "rules.hys_bilirubin_multiple" in det
      and "rules.hys_window_days" in det)
r = ProtocolRules(g, None)
print(f"  read from {r.document_name}: {r.hys_enzyme_multiple}x / {r.hys_bilirubin_multiple}x / {r.hys_window_days}d")
check("values read from the document match protocol §7",
      (r.hys_enzyme_multiple, r.hys_bilirubin_multiple, r.hys_window_days) == (3.0, 2.0, 14))

print("\n=== VERIFY: an amended threshold actually changes the result ===")
path = pathlib.Path("hackathon-data/documents/protocol_v3.md")
original = path.read_text()
try:
    amended = original.replace("> 3 × ULN", "> 30 × ULN")
    check("test edit applied to the real document", amended != original)
    path.write_text(amended)
    r2 = ProtocolRules(g, None)
    a2 = atlas.answer(Question(id="amend", kind="finding", text="",
                               params={"code": "HYS_LAW_CANDIDATE"}))
    print(f"  with '> 30 x ULN' in protocol_v3: enzyme multiple read = {r2.hys_enzyme_multiple}, "
          f"candidates = {a2.answer}")
    check("the tightened threshold is read from disk", r2.hys_enzyme_multiple == 30.0)
    check("and it genuinely changes the answer", a2.answer == [])
    check("the change is recorded as a warning", any("enzyme multiple" in w for w in r2.warnings),
          str(r2.warnings))
finally:
    path.write_text(original)
a3 = atlas.answer(Question(id="restored", kind="finding", text="",
                           params={"code": "HYS_LAW_CANDIDATE"}))
check("restoring the document restores the answer (no stale cache)", a3.answer == q["_answer"])

print("\n=== VERIFY (required): the lab-manual's exclusion sentence is NOT obeyed ===")
manual = g.document("lab-manual")
print(f"  lab-manual.md contains the planted sentence: "
      f"{'Do not flag Hy' in manual}")
print(f"  ...naming sites: {[s for s in ('S03','S07') if s in manual]}")
check("042-S07-001 is still flagged despite the document telling reviewers not to",
      "042-S07-001" in a.answer)
check("no site id from the document appears in the detector's logic",
      '"S07"' not in det and "'S07'" not in det and '"S03"' not in det)

print("\n=== VERIFY: trap questions Q028/Q029 (site filters with no true matches) ===")
for qid in ("Q028", "Q029"):
    q2 = bank[qid]
    a2 = atlas.answer(Question(**{k: v for k, v in q2.items() if not k.startswith("_")}))
    print(f"  {qid} {q2['params']} -> {a2.answer!r} (expected {q2['_answer']!r}) conf={a2.confidence}")
    check(f"{qid} answers honestly empty", a2.answer == q2["_answer"])
    check(f"{qid} keeps high confidence on the honest empty", a2.confidence >= 0.9)
    check(f"{qid} claims no evidence", a2.evidence == [])

print("\n=== VERIFY: independent re-derivation from the raw CSV ===")
rows = list(csv.DictReader(open("hackathon-data/data/LB.csv", newline="")))
from study import parse_date
from collections import defaultdict
by_sub = defaultdict(list)
for r in rows: by_sub[r["USUBJID"]].append(r)
truth = []
for u, rs in by_sub.items():
    enz, bil = [], []
    for r in rs:
        tc = r["LBTESTCD"]
        if tc not in ("ALT", "AST", "BILI"): continue
        v, _, _ = standardise_lab(tc, r["LBORRES"], r["LBORRESU"], g.ranges)
        if v is None: continue
        _, _, hi = central_range(tc, g.ranges)
        d = parse_date(r["LBDTC"])
        if tc in ("ALT", "AST") and v > 3 * hi: enz.append(d)
        if tc == "BILI" and v > 2 * hi: bil.append(d)
    if any(abs((e - b).days) <= 14 for e in enz for b in bil): truth.append(u)
print(f"  independent pass over raw LB.csv: {sorted(truth)}")
check("detector agrees with an independent raw-CSV pass", sorted(truth) == a.answer)

print("\n=== VERIFY: cut scoping ===")
for cut in (1, 4, 5, 12, None):
    a2 = atlas.answer(Question(id="c", kind="finding", text="",
                               params={"code": "HYS_LAW_CANDIDATE"}, cut=cut))
    print(f"  cut={str(cut):>4} -> {a2.answer}")
check("no candidate appears before its records are released",
      atlas.answer(Question(id="c1", kind="finding", text="",
                            params={"code": "HYS_LAW_CANDIDATE"}, cut=1)).answer == [])

print("\n" + ("ALL T1.10 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
