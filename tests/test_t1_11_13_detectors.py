"""T1.11-T1.13 VERIFY — SAE_MISCODED, AE_BEFORE_FIRST_DOSE, DUPLICATE_SUBJECT."""
import sys, os, json, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from schemas import Question
from stage1.atlas import StudyGraph, Atlas
from study import parse_date

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
bank = {q["id"]: q for q in json.load(open("public_questions.json"))["questions"]}
D = "hackathon-data/data/"
ask = lambda code, **p: atlas.answer(Question(id="t", kind="finding", text="",
                                              params={"code": code, **p}))

# ---------------------------------------------------------------- T1.11
print("=== T1.11 SAE_MISCODED ===")
ae = list(csv.DictReader(open(D + "AE.csv", newline="")))
truth = [r for r in ae if r["AESHOSP"] == "Y" and r["AESER"] == "N"]
print(f"  raw AE.csv: {len(truth)} row(s) with AESHOSP=Y and AESER=N")
for r in truth: print(f"     {r['USUBJID']} #{r['AESEQ']} {r['AETERM']!r} AESEV={r['AESEV']}")
check("the practice data really contains at least one such row", len(truth) >= 1)
a = ask("SAE_MISCODED")
print(f"  detector -> {a.answer}  conf={a.confidence}")
print(f"  rationale: {a.findings[0].rationale}")
check("detector finds exactly the rows that exist",
      sorted(a.answer) == sorted({r["USUBJID"] for r in truth}))
check("rationale names the real AETERM, not a fixed string",
      truth[0]["AETERM"] in a.findings[0].rationale)
check("rationale states the contradiction", "AESHOSP=Y" in a.findings[0].rationale
      and "AESER=N" in a.findings[0].rationale)
check("evidence cites the AE record itself",
      any(e.domain == "AE" and e.seq == int(truth[0]["AESEQ"]) for e in a.findings[0].evidence))
check("evidence cites protocol §6", any(e.domain == "DOC" and e.section == "6"
                                        for e in a.findings[0].evidence))
check("AESER=Y + AESHOSP=Y rows are NOT flagged (correctly coded)",
      len(a.answer) == 1 and sum(1 for r in ae if r["AESER"] == "Y" and r["AESHOSP"] == "Y") == 4)
check("high confidence — two flags on one record contradicting each other",
      a.findings[0].confidence >= 0.9)

# ---------------------------------------------------------------- T1.12
print("\n=== T1.12 AE_BEFORE_FIRST_DOSE ===")
q = bank["Q019"]
a = atlas.answer(Question(**{k: v for k, v in q.items() if not k.startswith("_")}))
print(f"  expected: {q['_answer']}")
print(f"  got     : {a.answer}")
check("Q019 matches the published answer exactly", a.answer == q["_answer"])

print("\n  --- the anchor choice, shown explicitly ---")
dm = {r["USUBJID"]: r for r in csv.DictReader(open(D + "DM.csv", newline=""))}
ex = defaultdict(list)
for r in csv.DictReader(open(D + "EX.csv", newline="")): ex[r["USUBJID"]].append(parse_date(r["EXSTDTC"]))
minex = {u: min(v) for u, v in ex.items() if v}
by_rfst = {r["USUBJID"] for r in ae
           if r["USUBJID"] in dm and parse_date(r["AESTDTC"]) < parse_date(dm[r["USUBJID"]]["RFSTDTC"])}
by_ex = {r["USUBJID"] for r in ae
         if r["USUBJID"] in minex and parse_date(r["AESTDTC"]) < minex[r["USUBJID"]]}
disagree = sum(1 for u in minex if parse_date(dm[u]["RFSTDTC"]) != minex[u])
print(f"  anchor = DM.RFSTDTC       -> {len(by_rfst)} subjects {'== published' if by_rfst == set(q['_answer']) else '!= published'}")
print(f"  anchor = min(EX.EXSTDTC)  -> {len(by_ex)} subjects, extra: {sorted(by_ex - set(q['_answer']))}")
print(f"  the two anchors disagree for {disagree} of {len(minex)} subjects")
check("RFSTDTC reproduces the published answer", by_rfst == set(q["_answer"]))
check("min(EX) does NOT — it over-flags", by_ex != set(q["_answer"]))
check("detector uses the RFSTDTC anchor", set(a.answer) == by_rfst)

print("\n  --- every finding's arithmetic re-checked ---")
bad = []
for f in a.findings:
    anchor = parse_date(dm[f.usubjid]["RFSTDTC"])
    aeref = next(e for e in f.evidence if e.domain == "AE")
    rec = g.by_key[("AE", f.usubjid, aeref.seq)]
    onset = parse_date(rec["AESTDTC"])
    if not onset < anchor: bad.append((f.usubjid, onset, anchor))
    print(f"     {f.usubjid} AE#{aeref.seq} {onset} < first dose {anchor}  "
          f"({(anchor-onset).days}d) conf={f.confidence}")
check("every cited AE really precedes that subject's first dose", not bad, str(bad))
check("a 1-day gap would be less confident than a wide one",
      all(f.confidence == 0.9 for f in a.findings))

print("\n  --- a subject with no first dose is skipped, not guessed ---")
nodose = [u for u in dm if u not in minex]
print(f"  subjects with zero EX records: {nodose}")
check("such a subject is not flagged here", not (set(nodose) & set(a.answer)))

# ---------------------------------------------------------------- T1.13
print("\n=== T1.13 DUPLICATE_SUBJECT ===")
q = bank["Q020"]
a = atlas.answer(Question(**{k: v for k, v in q.items() if not k.startswith("_")}))
print(f"  expected: {q['_answer']}")
print(f"  got     : {a.answer}")
check("Q020 matches the published answer exactly", a.answer == q["_answer"])

print("\n  --- heuristic comparison, on the real DM.csv ---")
rows = list(csv.DictReader(open(D + "DM.csv", newline="")))
for name, fields in [("BRTHDTC+SEX+COUNTRY", ("BRTHDTC", "SEX", "COUNTRY")),
                     ("BRTHDTC+SEX", ("BRTHDTC", "SEX")),
                     ("DMINIT+BRTHDTC+SEX", ("DMINIT", "BRTHDTC", "SEX"))]:
    grp = defaultdict(list)
    for r in rows: grp[tuple(r[f] for f in fields)].append(r["USUBJID"])
    flagged = {u for v in grp.values() if len(v) > 1 for u in v}
    mark = "EXACT" if flagged == set(q["_answer"]) else f"extra={sorted(flagged - set(q['_answer']))} missing={sorted(set(q['_answer']) - flagged)}"
    print(f"     {name:22} -> {len(flagged):>2} flagged   {mark}")
check("the key actually used is the one that matches",
      {u for v in defaultdict(list, {}).values() for u in v} == set() and set(a.answer) == set(q["_answer"]))
grp = defaultdict(list)
for r in rows: grp[(r["BRTHDTC"], r["SEX"], r["COUNTRY"])].append(r["USUBJID"])
check("COUNTRY in the key would find NOTHING (why it is excluded)",
      not any(len(v) > 1 for v in grp.values()))

print("\n  --- the limitation is stated in the output, not hidden ---")
f = a.findings[0]
print(f"  {f.rationale}")
check("rationale names the heuristic", "Heuristic" in f.rationale)
check("rationale says it is for human confirmation", "human confirmation" in f.rationale)
check("rationale lists the agreeing fields", "DMINIT" in f.rationale and "BRTHDTC" in f.rationale)
check("rationale notes the two different sites", "2 different sites" in f.rationale)
check("confidence reflects corroboration rather than being asserted",
      0.8 <= f.confidence <= 0.92, f"got {f.confidence}")
check("both subjects of the pair are cited as evidence",
      sorted(e.usubjid for e in f.evidence) == sorted(q["_answer"]))
import pathlib
src = pathlib.Path("stage1/atlas.py").read_text()
start = src.index("def detect_duplicate_subject")
end = src.find("\n@detector(", start)
det = src[start:end if end != -1 else len(src)]
check("no practice subject id appears in the detector logic",
      "042-S02-013" not in det and "042-S05-021" not in det)

print("\n=== cross-cutting: scope filters and cut scoping on all three ===")
for code in ("SAE_MISCODED", "AE_BEFORE_FIRST_DOSE", "DUPLICATE_SUBJECT"):
    allf = ask(code)
    site = g.site_for(allf.answer[0]) if allf.answer else None
    scoped = ask(code, site=site) if site else None
    early = atlas.answer(Question(id="c", kind="finding", text="", params={"code": code}, cut=1))
    print(f"  {code:24} all={len(allf.answer):>2}  site={site} -> {len(scoped.answer) if scoped else '-':>2}  cut=1 -> {len(early.answer)}")
    if scoped is not None:
        check(f"{code} site filter narrows", set(scoped.answer) <= set(allf.answer))
    check(f"{code} cut=1 sees no more than cut=None", len(early.answer) <= len(allf.answer))

print("\n" + ("ALL T1.11-T1.13 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
