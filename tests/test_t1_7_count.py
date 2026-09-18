"""T1.7 VERIFY — count metrics reproduced against the organiser's public answers."""
import sys, os, json, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Answer, Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
atlas = Atlas(g)
bank = json.load(open("public_questions.json"))["questions"]

print("=== VERIFY (required): reproduce the organiser's published Q001-Q003 ===")
for q in bank:
    if q["kind"] != "count":
        continue
    expected = q["_answer"]
    question = Question(**{k: v for k, v in q.items() if not k.startswith("_")})
    a = atlas.answer(question)
    print(f"  {question.id} params={question.params}")
    print(f"     got={a.answer!r}  expected={expected!r}  evidence={len(a.evidence)} refs  conf={a.confidence}")
    check(f"{question.id} count matches the published answer", a.answer == expected,
          f"got {a.answer}, expected {expected}")
    check(f"{question.id} evidence count equals the count", len(a.evidence) == a.answer)
    for e in a.evidence:
        rec = g.by_key.get(("DS", e.usubjid, e.seq))
        ok = rec is not None and rec["DSDECOD"] == "DISCONTINUED" and rec["DSTERM"] == "ADVERSE EVENT"
        if not ok: check(f"{question.id} evidence {e.usubjid}#{e.seq} really shows it", False)
    check(f"{question.id} every cited record genuinely shows a discontinuation for AE", True)
    if a.evidence:
        e = a.evidence[0]; rec = g.by_key[("DS", e.usubjid, e.seq)]
        print(f"     e.g. {e.domain}:{e.usubjid}:{e.seq} -> DSDECOD={rec['DSDECOD']} DSTERM={rec['DSTERM']!r}")

print("\n=== VERIFY: zero is answered as zero, with high confidence and clean evidence ===")
q2 = next(q for q in bank if q.get("_answer") == 0 and q["kind"] == "count")
a = atlas.answer(Question(**{k: v for k, v in q2.items() if not k.startswith("_")}))
print(f"  {q2['id']}: answer={a.answer!r} evidence={a.evidence} confidence={a.confidence}")
check("an honest zero keeps high confidence", a.answer == 0 and a.confidence >= 0.9)
import run_local_harness as H
ev, txt = H.evidence_shape_ok(a)
check("harness scores a zero-with-no-evidence as clean", ev == 1.0, f"{ev} ({txt})")

print("\n=== VERIFY: the count agrees with an independent pass over the raw CSV ===")
rows = list(csv.DictReader(open("hackathon-data/data/DS.csv", newline="")))
for site in sorted({r["USUBJID"].split("-")[1] for r in rows}):
    truth = sum(1 for r in rows if r["USUBJID"].split("-")[1] == site
                and r["DSDECOD"] == "DISCONTINUED" and r["DSTERM"] == "ADVERSE EVENT")
    a = atlas.answer(Question(id=f"s-{site}", kind="count", text="",
                              params={"metric": "discontinued_ae", "site": site}))
    print(f"  {site}: atlas={a.answer:>2}  raw csv={truth:>2}  {'ok' if a.answer==truth else 'MISMATCH'}")
    check(f"{site} agrees with raw CSV", a.answer == truth)
total = atlas.answer(Question(id="all", kind="count", text="", params={"metric": "discontinued_ae"}))
truth = sum(1 for r in rows if r["DSDECOD"] == "DISCONTINUED" and r["DSTERM"] == "ADVERSE EVENT")
check(f"no site filter -> study total ({truth})", total.answer == truth, f"got {total.answer}")

print("\n=== VERIFY: coded-value matching tolerates case and spacing ===")
from stage1.atlas import _norm
check("_norm folds case and whitespace",
      _norm(" Adverse   Event ") == "ADVERSE EVENT" and _norm(None) == "")

print("\n=== VERIFY: cut scoping ===")
for cut in (1, 6, 12, None):
    a = atlas.answer(Question(id="c", kind="count", text="",
                              params={"metric": "discontinued_ae"}, cut=cut))
    visible = len(g.records("DS", cut=cut))
    print(f"  cut={str(cut):>4}: count={a.answer:>2}  (DS rows visible: {visible})")
check("an early cut sees no more than a late one",
      atlas.answer(Question(id="a", kind="count", text="", params={"metric":"discontinued_ae"}, cut=1)).answer
      <= atlas.answer(Question(id="b", kind="count", text="", params={"metric":"discontinued_ae"}, cut=12)).answer)

print("\n=== VERIFY: registry is extensible in one function + one entry ===")
check("metrics registry is a plain name -> function dict",
      isinstance(atlas.metrics, dict) and "discontinued_ae" in atlas.metrics)
check("unknown metric still answered honestly",
      atlas.answer(Question(id="u", kind="count", text="", params={"metric":"nope"})).confidence == 0.0)

print("\n" + ("ALL T1.7 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
