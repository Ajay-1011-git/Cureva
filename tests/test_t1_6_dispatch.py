"""T1.6 VERIFY — Atlas dispatch skeleton and honest failure shape."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Answer, Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
atlas = Atlas(g)

print("=== VERIFY (required): unknown metric returns a valid Answer, not an exception ===")
q = Question(id="x", kind="count", text="", params={"metric": "nonexistent"})
a = atlas.answer(q)
print(f"  {a.model_dump()}")
check("returned an Answer, did not raise", isinstance(a, Answer))
check("schema-valid", Answer.model_validate(a.model_dump()) is not None)
check("answer is None or 0", a.answer in (None, 0))
check("confidence is low", a.confidence <= 0.1, f"got {a.confidence}")
check("question_id echoed", a.question_id == "x")
check("text explains the problem", "nonexistent" in a.text)
check("no evidence claimed", a.evidence == [])

print("\n=== VERIFY: an unknown question kind is refused honestly ===")
q = Question.model_construct(id="y", kind="whatever", text="", params={}, cut=None)
a = atlas.answer(q)
print(f"  {a.model_dump()}")
check("unknown kind -> valid low-confidence Answer",
      isinstance(a, Answer) and a.answer is None and a.confidence == 0.0)

print("\n=== VERIFY: a detector that explodes does not escape answer() ===")
def boom(self, question, params, deadline):
    raise RuntimeError("synthetic detector failure")
atlas.metrics["boom"] = boom
a = atlas.answer(Question(id="z", kind="count", text="", params={"metric": "boom"}))
print(f"  {a.model_dump()}")
check("exception converted to an Answer", isinstance(a, Answer) and a.answer is None)
check("confidence 0 on failure", a.confidence == 0.0)
check("failure reason preserved in text", "synthetic detector failure" in a.text)
del atlas.metrics["boom"]

print("\n=== VERIFY: trap is not a separate code path ===")
import inspect
src = inspect.getsource(Atlas.answer)
check("answer() routes finding and trap to the same handler",
      'question.kind in ("finding", "trap")' in src)
check("no branch anywhere keys on the literal 'trap' alone",
      'kind == "trap"' not in inspect.getsource(Atlas))

print("\n=== VERIFY: time limit constants match the harness ===")
from stage1.atlas import TIME_LIMIT_SECONDS, SOFT_BUDGET_SECONDS
import run_local_harness
check("TIME_LIMIT_SECONDS matches harness LIMITS",
      TIME_LIMIT_SECONDS == run_local_harness.LIMITS["seconds"],
      f"{TIME_LIMIT_SECONDS} vs {run_local_harness.LIMITS['seconds']}")
check("soft budget leaves headroom", SOFT_BUDGET_SECONDS < TIME_LIMIT_SECONDS)

print("\n=== VERIFY: graded module imports nothing that can touch the network ===")
import stage1.atlas as A
mod_src = open(A.__file__).read()
for banned in ("import requests", "import httpx", "from groq", "import groq",
               "import intake", "from intake", "import graph", "from graph",
               "import urllib", "import socket", "sarvam"):
    check(f"no {banned!r} in stage1/atlas.py", banned not in mod_src)

print("\n=== VERIFY: not-yet-built kinds fail honestly rather than crash ===")
for kind in ("lookup", "finding", "trap"):
    a = atlas.answer(Question(id=f"q-{kind}", kind=kind, text="", params={}))
    ok = isinstance(a, Answer) and a.confidence == 0.0
    print(f"  {kind:8} -> answer={a.answer!r} conf={a.confidence} text={a.text[:60]!r}")
    check(f"{kind} returns a valid Answer (stub stage)", ok)

print("\n" + ("ALL T1.6 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
