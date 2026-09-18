"""T1.34 VERIFY — answering a plain-English question with no model at all.

`Atlas.answer()` routes on structured params and never reads the question's
sentence. That is the right default, but it means a question whose intent
lives only in its wording cannot be answered at all.

`Atlas.ask()` closes that gap with regular expressions and the keyword tables
in `stage1/atlas.py` — no LLM, no network, no API key. The test that matters
is not "does it parse a sentence", it is "does the sentence alone reach the
same answer the graded params reach". So this strips the params off all ten
public questions and scores the text-only path against the organiser's own
published answers.

It also checks the half that keeps the widening safe: a question it cannot
work out is refused, not guessed at.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Question
from stage1.atlas import Atlas, StudyGraph, resolve_params_from_text

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


graph = StudyGraph(DATA_DIR)
graph.build(None)
atlas = Atlas(graph)

bank = json.load(open("public_questions.json"))["questions"]

print("=== the public bank, answered from the SENTENCE ONLY ===")
print("    (params discarded; nothing but the English text is passed in)\n")

matched = 0
for q in bank:
    expected = q["_answer"]
    answer = atlas.ask(q["text"])
    got = answer.answer

    # A finding/trap answer is a set of subjects; order is not meaningful.
    if isinstance(expected, list) and isinstance(got, list):
        ok = sorted(expected) == sorted(got)
    else:
        ok = expected == got
    matched += bool(ok)

    shown = got if not isinstance(got, list) or len(got) <= 3 else f"{got[:3]}... ({len(got)})"
    print(f"  {'OK  ' if ok else 'MISS'} {q['id']} {q['kind']:7} {q['text'][:58]}")
    print(f"        expected {expected if not isinstance(expected, list) or len(expected) <= 3 else str(expected[:3]) + f'... ({len(expected)})'}")
    print(f"        got      {shown}   evidence={len(answer.evidence)} conf={answer.confidence}")

print()
check("every public question is answered correctly from its text alone",
      matched == len(bank), f"({matched}/{len(bank)})")

# The two traps are the ones worth calling out separately: answering "[]" from
# a sentence is only impressive if it came from running the detector, not from
# failing to parse.
traps = [q for q in bank if q["kind"] == "trap"]
trap_ok = all(atlas.ask(q["text"]).answer == [] for q in traps)
trap_routed = all(resolve_params_from_text(q["text"], graph).get("code") for q in traps)
check("both traps return an empty list, not a parse failure", trap_ok and trap_routed,
      f"({len(traps)} traps, each routed to a real detector)")

print()
print("=== refusals: what it will NOT answer ===")
unresolvable = [
    "What is the airspeed velocity of an unladen swallow?",
    "Tell me about the study.",
    "How many subjects are there?",
    "Is this trial going well?",
]
for text in unresolvable:
    answer = atlas.ask(text)
    print(f"  {text[:52]:54} -> answer={answer.answer!r} conf={answer.confidence}")
check("a question it cannot work out is refused at zero confidence",
      all(atlas.ask(t).answer is None and atlas.ask(t).confidence == 0.0
          for t in unresolvable))

# Ambiguity must refuse rather than pick. A sentence naming two different
# findings is not a question this system can route.
ambiguous = resolve_params_from_text(
    "Which subjects had a dosing error and also took a prohibited medication?", graph)
check("a sentence naming two findings refuses rather than picking one",
      ambiguous == {}, f"({ambiguous})")

print()
print("=== params still win over the sentence ===")
# A sentence about Hy's law, with params that say otherwise. The params must
# decide, or the graded path would be at the mercy of the wording.
conflict = atlas.answer(Question(
    id="conflict", kind="finding",
    text="Which subjects meet potential Hy's law criteria?",
    params={"code": "DUPLICATE_SUBJECT"}))
check("explicit params override anything the text implies",
      sorted(conflict.answer) == ["042-S02-013", "042-S05-021"],
      f"(got {conflict.answer})")

# And a fully-specified question must be untouched by the enrichment path.
plain = Question(id="p", kind="finding", text="anything at all",
                 params={"code": "HYS_LAW_CANDIDATE"})
check("a fully-specified question is returned unchanged by enrichment",
      atlas._enrich_from_text(plain) is plain)

print()
print("=== no model involved ===")
import inspect

import stage1.atlas as atlas_mod
src = inspect.getsource(atlas_mod)
check("stage1/atlas.py imports no LLM client and makes no network call",
      not any(t in src for t in ("import groq", "from groq", "openai", "requests.post",
                                 "httpx", "chat.completions")))

print("\n" + ("ALL T1.34 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
