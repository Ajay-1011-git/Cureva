"""T2.17 VERIFY — every finding keeps a verdict when Act 3 is rate-limited.

The property under test is the one that lets Act 3 sit inside the graded path
at all: Groq failing, in any of the ways it actually fails, must cost narrative
and nothing else. Not a missing verdict, not a changed verdict, not an
exception escaping into `run_cycle()`.

The burst is simulated rather than really fired. Two reasons, and neither is
squeamishness about the quota: a live burst would assert on Groq's mood on the
day, and the failure modes worth testing (429 mid-round, timeout, malformed
response, hard exception) do not arrive on demand. The one thing that *is*
verified against reality is the rate-limit classifier, which is checked against
Groq's real 429 payload -- captured live during this build.
"""
import os
import shutil
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tribunal
from stage1.atlas import Atlas, StudyGraph
from stage2 import ReviewCrew
from stage2.crew import ALWAYS_ESCALATE
from tribunal.client import is_rate_limit
from tribunal.models import TribunalTranscript

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")
CUT, PROTOCOL_VERSION = 9, 3

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


# ---------------------------------------------------------------------------
# 1. The classifier, against Groq's real 429 body (captured live).
# ---------------------------------------------------------------------------
print("=== T2.17 — Act 3 under rate limiting ===\n")


class RateLimitError(Exception):
    pass


real_429 = RateLimitError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on "
    "tokens per minute (TPM): Limit 8000, Used 7535, Requested 1094.', "
    "'type': 'tokens', 'code': 'rate_limit_exceeded'}}")

check("a real Groq 429 is classified as a rate limit", is_rate_limit(real_429))
check("an ordinary failure is not", not is_rate_limit(ValueError("bad json")))
check("a 401 is not treated as a rate limit",
      not is_rate_limit(Exception("Error code: 401 - Invalid API Key")))

# ---------------------------------------------------------------------------
# 2. A cycle where every Act 3 attempt fails, in a different way each time.
# ---------------------------------------------------------------------------
print()
attempts = Counter()
real_deliberate = tribunal.deliberate


def flaky_deliberate(atlas, finding, finding_id, cut, **kwargs):
    """Cycle through the failure modes Groq really produces."""
    n = attempts["calls"]
    attempts["calls"] += 1
    mode = n % 4
    if mode == 0:
        attempts["rate_limited"] += 1
        return TribunalTranscript(finding_id=finding_id, ran=False,
                                  skip_reason="Groq rate limit (tokens per minute) reached")
    if mode == 1:
        attempts["timed_out"] += 1
        return TribunalTranscript(finding_id=finding_id, ran=False,
                                  skip_reason="timed out after 12s")
    if mode == 2:
        attempts["no_verdict"] += 1
        return TribunalTranscript(finding_id=finding_id, ran=False,
                                  skip_reason="response failed schema validation")
    attempts["raised"] += 1
    raise RateLimitError("429 rate_limit_exceeded — raised straight out of tribunal/")


work = tempfile.mkdtemp(prefix="cureva-t2-17-")
try:
    tribunal.deliberate = flaky_deliberate

    graph = StudyGraph(DATA_DIR)
    crew = ReviewCrew(DATA_DIR, Atlas(graph), state_dir=work,
                      tribunal=True, tribunal_budget=8)
    report = crew.run_cycle(cut=CUT, protocol_version=PROTOCOL_VERSION)

    verdicts = crew.last_verdicts
    escalation_worthy = [v for v in verdicts if v.escalate]
    traced = Counter(e.decision_type for e in crew.trace.current_cycle)

    print(f"  Act 3 attempts: {dict(attempts)}")
    print(f"  findings={len(report.findings)} verdicts={len(verdicts)} "
          f"escalation-worthy={len(escalation_worthy)}")
    print(f"  tribunal_verdict lines={traced.get('tribunal_verdict', 0)} "
          f"tribunal_skipped lines={traced.get('tribunal_skipped', 0)}\n")

    check("the cycle returned a report despite every Act 3 attempt failing",
          report is not None and len(report.findings) > 0)
    check("every finding has a verdict",
          len(verdicts) == len(report.findings),
          f"({len(verdicts)} verdicts for {len(report.findings)} findings)")
    check("no finding was left without a verdict",
          all(v.rule for v in verdicts))
    check("zero Act 3 attempts completed", traced.get("tribunal_verdict", 0) == 0)
    check("every failed attempt left a trace line",
          traced.get("tribunal_skipped", 0) >= attempts["calls"],
          f"({traced.get('tribunal_skipped', 0)} lines for {attempts['calls']} attempts)")
    check("the exception raised inside tribunal/ never reached run_cycle()",
          attempts["raised"] > 0)
    check("escalations were still raised normally",
          len(report.escalations) > 0, f"({len(report.escalations)})")
    check("safety-critical codes are still all escalation-worthy",
          all(v.escalate for v in verdicts if v.finding.code in ALWAYS_ESCALATE))
    check("token count stayed honest at zero when nothing completed",
          report.tokens_used == 0, f"({report.tokens_used})")

    # ----------------------------------------------------------------
    # 3. The same cut with Act 3 off. The verdicts must be identical.
    # ----------------------------------------------------------------
    crew_off = ReviewCrew(DATA_DIR, Atlas(StudyGraph(DATA_DIR)),
                          state_dir=os.path.join(work, "off"), tribunal=False)
    report_off = crew_off.run_cycle(cut=CUT, protocol_version=PROTOCOL_VERSION)
    off_worthy = {v.finding_id for v in crew_off.last_verdicts if v.escalate}
    on_worthy = {v.finding_id for v in escalation_worthy}

    print()
    check("the escalation-worthy set is identical with Act 3 failing and Act 3 off",
          on_worthy == off_worthy,
          f"({len(on_worthy)} vs {len(off_worthy)})")
    check("the finding set is identical too",
          [f.fingerprint() for f in report.findings]
          == [f.fingerprint() for f in report_off.findings])
finally:
    tribunal.deliberate = real_deliberate
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("ALL T2.17 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
