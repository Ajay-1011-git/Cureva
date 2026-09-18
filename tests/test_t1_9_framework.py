"""T1.9 VERIFY — finding/trap detector framework."""
import sys, os, inspect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Answer, Question, Finding, RecordRef, FindingCode
from stage1.atlas import StudyGraph, Atlas, DETECTORS, detector

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
atlas = Atlas(g)

print("=== VERIFY (required): an unknown code returns an honest empty Answer ===")
a = atlas.answer(Question(id="q", kind="finding", text="", params={"code": "NOT_A_REAL_CODE"}))
print(f"  {a.model_dump()}")
check("valid Answer, no crash", isinstance(a, Answer) and Answer.model_validate(a.model_dump()))
check("empty list answer", a.answer == [])
check("low confidence — we did not look, so we cannot claim nothing is there",
      a.confidence == 0.0, f"got {a.confidence}")
check("text says plainly that it is not claimed", "does not claim" in a.text)
check("no evidence", a.evidence == [] and a.findings == [])

print("\n=== VERIFY: 'we did not look' is distinguished from 'nothing is there' ===")
@detector("HYS_LAW_CANDIDATE")
def _tmp(graph, site, usubjid, cut):
    return []
atlas2 = Atlas(g)
nothing = atlas2.answer(Question(id="n", kind="finding", text="", params={"code": "HYS_LAW_CANDIDATE"}))
print(f"  detector ran, found nothing : conf={nothing.confidence}  text={nothing.text!r}")
print(f"  no detector at all          : conf={a.confidence}  text={a.text[:60]!r}")
check("a detector that ran and found nothing is CONFIDENT", nothing.confidence >= 0.9)
check("a code with no detector is NOT confident", a.confidence == 0.0)
check("the two are different answers", nothing.confidence != a.confidence)
DETECTORS.pop("HYS_LAW_CANDIDATE")

print("\n=== VERIFY: findings flow into answer/findings/evidence correctly ===")
@detector("DOSING_ERROR")
def _fake(graph, site, usubjid, cut):
    return [
        Finding(code="DOSING_ERROR", usubjid="042-S01-001", site="S01", rationale="synthetic A",
                confidence=0.9, evidence=[RecordRef(domain="EX", usubjid="042-S01-001", seq=1)]),
        Finding(code="DOSING_ERROR", usubjid="042-S02-001", site="S02", rationale="synthetic B",
                confidence=0.7, evidence=[RecordRef(domain="EX", usubjid="042-S02-001", seq=2),
                                          RecordRef(domain="EX", usubjid="042-S01-001", seq=1)]),
    ]
at = Atlas(g)
a = at.answer(Question(id="f", kind="finding", text="", params={"code": "DOSING_ERROR"}))
print(f"  answer     : {a.answer}")
print(f"  findings   : {len(a.findings)}   evidence: {[(e.domain,e.usubjid,e.seq) for e in a.evidence]}")
print(f"  confidence : {a.confidence}   text: {a.text[:80]!r}")
check("answer is a sorted list of USUBJIDs", a.answer == ["042-S01-001", "042-S02-001"])
check("findings carried through", len(a.findings) == 2)
check("evidence flattened and de-duplicated", len(a.evidence) == 2)
check("confidence is the mean of the findings", a.confidence == 0.8)

print("\n=== VERIFY: site / usubjid scope filters ===")
a = at.answer(Question(id="s", kind="finding", text="", params={"code": "DOSING_ERROR", "site": "S01"}))
check("site filter narrows the answer", a.answer == ["042-S01-001"], str(a.answer))
a = at.answer(Question(id="u", kind="finding", text="", params={"code": "DOSING_ERROR", "usubjid": "042-S02-001"}))
check("usubjid filter narrows the answer", a.answer == ["042-S02-001"], str(a.answer))
a = at.answer(Question(id="t", kind="trap", text="", params={"code": "DOSING_ERROR", "site": "S99"}))
print(f"  trap-shaped (site with no matches): answer={a.answer} conf={a.confidence} evidence={a.evidence}")
check("a scope with no matches -> empty list, empty evidence", a.answer == [] and a.evidence == [])
check("that honest empty is high-confidence", a.confidence >= 0.9)
import run_local_harness as H
ev, _ = H.evidence_shape_ok(a)
check("the harness scores that empty answer as clean evidence", ev == 1.0)

print("\n=== VERIFY: trap and finding kinds take the identical path ===")
kw = {"text": "", "params": {"code": "DOSING_ERROR", "site": "S01"}}
f_ans = at.answer(Question(id="x", kind="finding", **kw))
t_ans = at.answer(Question(id="x", kind="trap", **kw))
check("identical params give byte-identical answers regardless of kind",
      f_ans.model_dump() == t_ans.model_dump())
DETECTORS.pop("DOSING_ERROR")

print("\n=== VERIFY: a detector that raises is contained ===")
@detector("DUPLICATE_SUBJECT")
def _boom(graph, site, usubjid, cut):
    raise RuntimeError("synthetic detector crash")
at = Atlas(g)
a = at.answer(Question(id="b", kind="finding", text="", params={"code": "DUPLICATE_SUBJECT"}))
print(f"  answer={a.answer!r} conf={a.confidence} text={a.text!r}")
check("crash becomes a valid Answer", isinstance(a, Answer) and a.confidence == 0.0)
check("crashed finding answers with [] not None (matches the kind's type)", a.answer == [])
check("reason preserved", "synthetic detector crash" in a.text)
DETECTORS.pop("DUPLICATE_SUBJECT")

print("\n=== VERIFY: registry shape and Stage-1 scope ===")
at = Atlas(g)
print(f"  registered detectors: {sorted(at.detectors) or 'none yet (T1.10-T1.19)'}")
check("detectors is a plain code -> function dict", isinstance(at.detectors, dict))
out_of_scope = {"SAE_UNESCALATED", "LAB_UNIT_CORRUPTION", "IMPLAUSIBLE_SITE_PATTERN",
                "LATE_DATA_ENTRY", "DOCUMENT_TAMPERED"}
check("no Stage 2/3 code is registered in Stage 1",
      not (set(at.detectors) & out_of_scope), str(set(at.detectors) & out_of_scope))
check("every registered code is a real schemas.FindingCode",
      set(at.detectors) <= set(FindingCode.__args__), str(set(at.detectors) - set(FindingCode.__args__)))

print("\n" + ("ALL T1.9 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
