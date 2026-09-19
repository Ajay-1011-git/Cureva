"""T3.17 VERIFY — the optional polish pass rewords prose and never changes a fact.

Four independent ways this returns the template untouched, and every one is a
normal outcome rather than an error:

  1. the token ledger cannot afford the call — and the call is then NEVER
     ATTEMPTED, so the budget is not learned from a rate-limit error;
  2. Groq is unreachable, unconfigured, or raises;
  3. the response is empty or implausibly short;
  4. the polished text does not state exactly the facts the template did.

All four are exercised here with a stub provider, so this test runs with no
Groq key at all. The live call is exercised separately and only when a key is
present — the graded path never needs one.

Run: .venv/bin/python tests/test_t3_17_polish.py
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execute.polish import (facts_in, polish_artifact, verify_facts_preserved)
from execute.templates import draft_artifact
from schemas import RecordRef
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.budget import POLISH_ESTIMATED_TOKENS, TokenLedger
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


class StubProvider:
    """Stands in for Groq. Records calls; returns whatever it is told to."""

    def __init__(self, reply: str | None = None, raises: Exception | None = None,
                 tokens: int = 900):
        self.reply, self.raises, self.tokens, self.calls = reply, raises, tokens, 0
        outer = self

        class _Completions:
            @staticmethod
            def create(**kwargs):
                outer.calls += 1
                if outer.raises:
                    raise outer.raises
                return type("R", (), {
                    "choices": [type("C", (), {
                        "message": type("M", (), {"content": outer.reply})()})()],
                    "usage": type("U", (), {"total_tokens": outer.tokens})()})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


state = Path(tempfile.mkdtemp(prefix="cureva-t317-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
watch.run_period(cuts=range(1, 13))
memo = next(a for a in watch.artifacts.values() if a.kind == "IRB_MEMO")

# ==========================================================================
print("=" * 74)
print("PART 1 — the fact checker: what it accepts and what it refuses")
print("=" * 74)
base = ("Subject 042-S08-020, AGE=17, LBORRES=177,7 at cut 5, site S08, "
        "range 18-75. Code INCLUSION_VIOLATION.")
print(f"  facts extracted: {sorted(facts_in(base))}")
cases = [
    (True, "an en-dash range", base.replace("18-75", "18–75")),
    (True, "range spelled out", base.replace("18-75", "18 to 75")),
    (True, "a genuine reword",
     "At cut 5, subject 042-S08-020 at site S08 had AGE=17 and LBORRES=177,7, "
     "outside the 18-75 range. Code INCLUSION_VIOLATION."),
    (False, "site changed INSIDE the subject id", base.replace("S08-020", "S99-020")),
    (False, "a value changed", base.replace("AGE=17", "AGE=18")),
    (False, "a value dropped", "Subject 042-S08-020 at cut 5, site S08, range "
                               "18-75. Code INCLUSION_VIOLATION."),
    (False, "a deadline invented", base.replace("cut 5", "cut 5, report within 30 days")),
    (False, "the finding code softened away", base.replace(" Code INCLUSION_VIOLATION.", "")),
]
for expect_ok, label, candidate in cases:
    ok, problems = verify_facts_preserved(base, candidate)
    print(f"      {'ACCEPT' if ok else 'REJECT'}  {label:38} {problems}")
    check(f"  {label}: {'accepted' if expect_ok else 'refused'}",
          ok == expect_ok, str(problems))

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the four ways the template ships unchanged")
print("=" * 74)

print("\n  1. the ledger cannot afford it — THE CALL IS NEVER ATTEMPTED")
broke = TokenLedger(ceiling=100)
spy = StubProvider(reply="irrelevant")
out = polish_artifact(memo, broke, client=spy)
print(f"      remaining={broke.remaining}, a call needs ~{POLISH_ESTIMATED_TOKENS}")
check("provider calls == 0", spy.calls == 0, str(spy.calls))
check("  source stays template_only", out.source == "template_only")
check("  text is byte-identical to the template", out.text == memo.text)
check("  nothing was debited for a call that never happened", broke.spent == 0)
check("  and the skip is recorded for the report", len(broke.skipped) == 1)
print(f"      recorded: {broke.skipped[0]}")

print("\n  2. the provider raises")
led = TokenLedger(ceiling=20_000)
boom = StubProvider(raises=RuntimeError("connection reset"))
out = polish_artifact(memo, led, client=boom)
check("the exception does not propagate", out is not None)
check("  template ships, tagged honestly", out.source == "template_only"
      and out.text == memo.text)
check("  and nothing was debited for a call that produced nothing",
      led.spent == 0, str(led.spent))

print("\n  3. the response comes back implausibly short")
led2 = TokenLedger(ceiling=20_000)
short = StubProvider(reply="Memo.", tokens=40)
out = polish_artifact(memo, led2, client=short)
check("a truncated reply is refused", out.source == "template_only")
check("  but the call IS paid for — it really happened", led2.spent == 40,
      str(led2.spent))

print("\n  4. the polished text alters a fact")
led3 = TokenLedger(ceiling=20_000)
tampered = memo.text.replace("AGE=17", "AGE=71")
liar = StubProvider(reply=tampered, tokens=880)
out = polish_artifact(memo, led3, client=liar)
check("an altered fact is refused and the polish discarded IN FULL",
      out.source == "template_only" and out.text == memo.text)
check("  and that call is paid for too", led3.spent == 880)

print("\n  ...and a faithful reword IS accepted")
led4 = TokenLedger(ceiling=20_000)
faithful = memo.text.replace("WHAT WAS FOUND", "FINDING")
good = StubProvider(reply=faithful, tokens=851)
out = polish_artifact(memo, led4, client=good)
check("a faithful reword is accepted", out.source == "polished", out.source)
check("  the text really changed", out.text != memo.text)
check("  the ledger is debited with the REAL count, not the estimate",
      led4.spent == 851, str(led4.spent))
check("  every other field is carried through unchanged",
      out.decision_id == memo.decision_id and out.kind == memo.kind
      and out.evidence == memo.evidence and out.facts == memo.facts)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — the graded path never needs a key")
print("=" * 74)
check("every artifact from a plain run_period() is template_only",
      all(a.source == "template_only" for a in watch.artifacts.values()),
      str({a.source for a in watch.artifacts.values()}))
check("  and the token ledger was never touched by the graded walk",
      watch.tokens.spent == 0, str(watch.tokens.spent))
print(f"  {len(watch.artifacts)} artifacts drafted, 0 tokens spent, no key required")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — one real Groq call (skipped when no key is present)")
print("=" * 74)
if not (os.environ.get("GROQ_API_KEY") or os.environ.get("groq_api_key")):
    print("  SKIPPED — no Groq key in the environment. This is the graded")
    print("  configuration: the whole of Stage 3 passes without one.")
else:
    live = TokenLedger(ceiling=20_000)
    result = polish_artifact(memo, live, client=None)
    print(f"  source       : {memo.source} -> {result.source}")
    print(f"  tokens spent : {live.spent} (estimate {POLISH_ESTIMATED_TOKENS})")
    print(f"  text changed : {result.text != memo.text}")
    ok, problems = verify_facts_preserved(memo.text, result.text)
    print(f"  facts intact : {ok} {problems}")
    check("the real call either polished faithfully or fell back honestly",
          result.source in ("polished", "template_only"))
    if result.source == "polished":
        check("  every fact survived the real rewording", ok, str(problems))
        check("  and the ledger recorded a real cost", live.spent > 0)
        print("\n  --- real polished output, first 10 lines ---")
        for line in result.text.splitlines()[:10]:
            print(f"      {line}")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
