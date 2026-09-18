"""T2.15 VERIFY — Round 3 discards exactly the unsupported claim, and no other.

The most safety-relevant test in this layer. Round 3 is the only thing standing
between a persona's confident prose and a human reading it as established fact,
so "it discarded something" is not good enough: it has to discard the claim that
is wrong and keep the ones that are right.

No network. The Round-1 verdicts are constructed by hand so the mismatch is
exact and the test is deterministic -- a live model might or might not cite a
bad record on any given run, and a gating test cannot depend on that.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Question, RecordRef
from stage1.atlas import Atlas, StudyGraph
from tribunal.models import (CrossExamChallenge, CrossExamResponse, PersonaVerdict)
from tribunal.round3 import arbitrate

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")
CUT = 9

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


print("=== T2.15 — deterministic arbitration ===\n")

graph = StudyGraph(DATA_DIR)
graph.build(CUT)
atlas = Atlas(graph)

finding = atlas.answer(Question(id="q", kind="finding", text="t",
                                params={"code": "HYS_LAW_CANDIDATE"}, cut=CUT)).findings[0]
real_refs = [e for e in finding.evidence if e.seq is not None]
print(f"finding: {finding.code} / {finding.usubjid}")
print(f"its real evidence: {[(e.domain, e.usubjid, e.seq) for e in real_refs]}\n")

# A record that genuinely exists but has nothing to do with this finding. Built
# from the subject's own CM rows so it is a real record, not a made-up id --
# the point is a *mismatch*, not a missing row, which is the harder case.
other_domain_rows = graph.records("VS", cut=CUT, usubjid=finding.usubjid)
assert other_domain_rows, "expected the subject to have VS rows"
unrelated = RecordRef(domain="VS", usubjid=finding.usubjid,
                      seq=other_domain_rows[0]["_seq"])
print(f"deliberately mismatched citation (real record, wrong finding): "
      f"{unrelated.domain}:{unrelated.usubjid}:{unrelated.seq}\n")

round1 = [
    PersonaVerdict(persona="SAFETY", finding_id="F-test", verdict="ESCALATE",
                   reasoning="ALT and bilirubin both exceed their thresholds on the same draw.",
                   cited_evidence=real_refs),
    PersonaVerdict(persona="CLINICAL_OPS", finding_id="F-test", verdict="ESCALATE",
                   reasoning="The lab values are internally consistent and not a transcription artefact.",
                   cited_evidence=real_refs),
    # The bad one: a real record that the Hy's law detector does not cite.
    PersonaVerdict(persona="REGULATORY", finding_id="F-test", verdict="MONITOR",
                   reasoning="The vital signs record shows the subject was stable, so no reporting duty arises.",
                   cited_evidence=[unrelated]),
]
round2 = [
    CrossExamResponse(persona="SAFETY", finding_id="F-test", challenges=[
        CrossExamChallenge(target_persona="REGULATORY",
                           claim_challenged="the subject was stable",
                           rebuttal="stability on vitals does not bear on a Hy's law signal")]),
    # A challenge against someone who never spoke, which is structurally void.
    CrossExamResponse(persona="CLINICAL_OPS", finding_id="F-test", challenges=[
        CrossExamChallenge(target_persona="SAFETY",
                           claim_challenged="the draw was same-day",
                           rebuttal="agreed, no dispute")]),
]

arb = arbitrate(atlas, finding, "F-test", round1, round2, CUT)

print(f"surviving claims: {len(arb.surviving_claims)}")
print(f"discarded claims: {len(arb.discarded_claims)}")
for d in arb.discarded_claims:
    print(f"   [{d.persona}] {d.reason_discarded}")
print(f"final verdict: {arb.final_verdict} (method: {arb.method})\n")

discarded_personas = [d.persona for d in arb.discarded_claims]

check("exactly one Round-1 claim was discarded",
      len(discarded_personas) == 1, f"(discarded: {discarded_personas})")
check("the discarded claim is REGULATORY's — the one citing the wrong record",
      discarded_personas == ["REGULATORY"])
check("SAFETY's well-cited claim survived",
      any("SAFETY]" in c for c in arb.surviving_claims))
check("CLINICAL_OPS's well-cited claim survived",
      any("CLINICAL_OPS]" in c for c in arb.surviving_claims))
check("the discard reason names the record that failed",
      any(f"{unrelated.domain}:{unrelated.usubjid}:{unrelated.seq}" in d.reason_discarded
          for d in arb.discarded_claims))
check("Round 3 used the deterministic evidence check",
      arb.method == "deterministic_evidence_check")
check("the discarded persona lost its vote, so the verdict is ESCALATE",
      arb.final_verdict == "ESCALATE",
      "(2 surviving ESCALATE votes, the MONITOR vote was struck)")
check("both Round-2 challenges survived as structural claims",
      sum(1 for c in arb.surviving_claims if "->" in c) == 2)

# Round 3 makes zero model calls. Assert it, rather than trusting the docstring.
import inspect

import tribunal.round3 as r3
src = inspect.getsource(r3)
check("round3.py contains no Groq/LLM call",
      not any(t in src for t in ("ask_json", "Groq", "chat.completions", "await ")))

print("\n" + ("ALL T2.15 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
