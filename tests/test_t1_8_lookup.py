"""T1.8 VERIFY — lookup window queries against the organiser's published answers."""
import sys, os, json, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas
from study import parse_date

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
atlas = Atlas(g)
bank = json.load(open("public_questions.json"))["questions"]

print("=== VERIFY (required): reproduce Q013 and Q014 exactly ===")
for q in bank:
    if q["kind"] != "lookup":
        continue
    expected = q["_answer"]
    question = Question(**{k: v for k, v in q.items() if not k.startswith("_")})
    a = atlas.answer(question)
    print(f"  {question.id} {question.params}")
    print(f"     expected : {expected}")
    print(f"     got      : {a.answer}")
    print(f"     text     : {a.text}")
    check(f"{question.id} matches the published answer exactly", a.answer == expected)
    check(f"{question.id} evidence count matches answer count", len(a.evidence) == len(a.answer))
    # every cited record must really sit inside the window
    anchor = g.visit_date(question.params["usubjid"], question.params["around_visit"], None)
    bad = []
    for e in a.evidence:
        rec = g.by_key[(e.domain, e.usubjid, e.seq)]
        d = g.record_date(rec, None)
        if d is None or abs((d - anchor).days) > question.params["window_days"]:
            bad.append((e.domain, e.seq, d))
    check(f"{question.id} every cited record really falls in the window", not bad, str(bad))

print("\n=== VERIFY: the rule is derived, not fitted — check the arithmetic by hand ===")
S = "042-S07-001"
anchor = g.visit_date(S, "WEEK12", None)
print(f"  anchor = {S} WEEK12 = {anchor}")
rows = list(csv.DictReader(open("hackathon-data/data/LB.csv", newline="")))
truth = sorted(f"LB:{S}:{r['LBSEQ']}" for r in rows
               if r["USUBJID"] == S and abs((parse_date(r["LBDTC"]) - anchor).days) <= 7)
ae = [r for r in csv.DictReader(open("hackathon-data/data/AE.csv", newline="")) if r["USUBJID"] == S]
ae_in = [r for r in ae if abs((parse_date(r["AESTDTC"]) - anchor).days) <= 7]
print(f"  independent CSV pass, LB within 7d: {truth}")
print(f"  independent CSV pass, AE within 7d: {[r['AESEQ'] for r in ae_in]} "
      f"(this subject's only AE is {(parse_date(ae[0]['AESTDTC'])-anchor).days} days away, correctly excluded)")
Q013_PARAMS = {"usubjid": S, "domains": ["LB", "AE"], "around_visit": "WEEK12", "window_days": 7}
a = atlas.answer(Question(id="hand", kind="lookup", text="", params=Q013_PARAMS))
check("atlas agrees with the independent CSV pass", sorted(a.answer) == truth,
      f"{sorted(a.answer)} vs {truth}")

print("\n=== VERIFY: window size actually changes the result ===")
for w in (0, 7, 30, 60, 365):
    a = atlas.answer(Question(id=f"w{w}", kind="lookup", text="", params={
        "usubjid": S, "domains": ["LB", "AE"], "around_visit": "WEEK12", "window_days": w}))
    doms = {i.split(":")[0] for i in a.answer}
    print(f"  window={w:>3}d -> {len(a.answer):>3} records {sorted(doms)}")
    if w == 0: check("window 0 still finds the same-date visit records", len(a.answer) == 6)
    if w == 60: check("window 60 pulls in the AE 54 days earlier", "AE" in doms)

print("\n=== VERIFY: honest empty answers ===")
cases = [
    ("visit the subject does not have", {"usubjid": S, "domains": ["LB"], "around_visit": "WEEK99", "window_days": 7}),
    ("subject not in the study",        {"usubjid": "NO-SUCH-SUBJ", "domains": ["LB"], "around_visit": "WEEK12", "window_days": 7}),
]
for label, params in cases:
    a = atlas.answer(Question(id="e", kind="lookup", text="", params=params))
    print(f"  {label:34} -> answer={a.answer} conf={a.confidence} text={a.text[:90]!r}")
    check(f"{label}: empty list, no evidence, no crash", a.answer == [] and a.evidence == [])
    check(f"{label}: honest empty is still confident", a.confidence >= 0.8)
a = atlas.answer(Question(id="nou", kind="lookup", text="", params={"domains": ["LB"]}))
check("missing usubjid -> honest empty, confidence 0", a.answer == [] and a.confidence == 0.0)

print("\n=== VERIFY: answer format matches the organiser's, and every id resolves ===")
a = atlas.answer(Question(id="f", kind="lookup", text="", params={
    "usubjid": S, "domains": ["LB", "VS", "EG", "EX", "AE", "CM", "DS", "MH", "DM"],
    "around_visit": "WEEK12", "window_days": 14}))
print(f"  {len(a.answer)} ids across all domains; sample: {a.answer[:4]} ... {a.answer[-2:]}")
bad = [i for i in a.answer if len(i.split(":")) != 3]
check("every id is DOMAIN:USUBJID:SEQ", not bad, str(bad))
check("all answers are strings", all(isinstance(i, str) for i in a.answer))
resolvable = all(g.by_key.get((i.split(":")[0], i.split(":")[1], int(i.split(":")[2]))) is not None
                 for i in a.answer if i.split(":")[0] != "DM")
check("every non-DM id resolves to a real record", resolvable)
check("MH (no date column) contributes nothing", not any(i.startswith("MH:") for i in a.answer))

print("\n=== VERIFY: runs for every subject without raising, across all visits ===")
subs = [r["USUBJID"] for r in g.by_domain["DM"]]
errs, total = [], 0
for u in subs:
    for v in ("SCREENING", "BASELINE", "WEEK12", "EOS"):
        try:
            a = atlas.answer(Question(id="s", kind="lookup", text="", params={
                "usubjid": u, "domains": ["LB", "AE"], "around_visit": v, "window_days": 7}))
            total += 1
            if a.confidence == 0.0 and "usubjid" in a.text: errs.append((u, v, a.text))
        except Exception as e:
            errs.append((u, v, repr(e)))
print(f"  {total} lookups across {len(subs)} subjects x 4 visits, {len(errs)} problems")
check("no lookup raised or failed structurally", not errs, str(errs[:2]))

print("\n=== VERIFY: cut scoping (042-S07-001 DM cut_available checked) ===")
dm_cut = g.by_usubjid_domain[(S, "DM")][0]["_cut"]
print(f"  {S} first becomes visible at cut {dm_cut} -- so an earlier cut correctly sees no subject")
for cut in (1, 6, None):
    a = atlas.answer(Question(id="c", kind="lookup", text="", params={
        "usubjid": S, "domains": ["LB"], "around_visit": "WEEK12", "window_days": 7}, cut=cut))
    print(f"  cut={str(cut):>4} -> {len(a.answer)} records   {a.text[:80]}")
early = atlas.answer(Question(id="c1", kind="lookup", text="", params=Q013_PARAMS, cut=1))
late = atlas.answer(Question(id="c12", kind="lookup", text="", params=Q013_PARAMS, cut=12))
check("an early cut sees no more than a late one", len(early.answer) <= len(late.answer))

print("\n" + ("ALL T1.8 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
