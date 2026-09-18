"""Round 3 — deterministic arbitration. Zero LLM calls, by design.

Rounds 1 and 2 are the only places in this system where a language model
influences what a human sees about a finding. Round 3 is the check on them,
and it would be worth nothing if it were itself a model call: asking a model
whether a model's claim is supported just moves the trust one step along.

So Round 3 asks `Atlas.verify_evidence()` instead -- the same check Stage 1
already has to get right for its own `Answer.evidence`. Every record a persona
cited is looked up in the graph at the cycle's cut and tested against the
finding's own detector. A claim citing a record that does not exist, is not
visible yet, or that the detector does not actually cite, is discarded with a
reason.

Two rules stated explicitly, because neither was specified upstream:

* **A Round-1 claim survives only if every record it cites verifies, and only
  if it cited something.** An uncited verdict is an opinion; Round 3's entire
  premise is that opinions do not survive an evidence check. This is strict on
  purpose and is visible in the transcript when it bites.
* **A Round-2 challenge is checked structurally, not factually.** The TRD's
  `CrossExamChallenge` carries no `RecordRef`s, so there is nothing to verify
  against the graph. A challenge survives if it targets a persona that really
  made a Round-1 claim. This is reported honestly as a structural check rather
  than dressed up as a fact-check it is not.

The final verdict is a majority of the personas still standing -- a persona
whose every claim was discarded does not get a vote. A tie, or nobody left,
resolves to ESCALATE: when the adjudication itself is inconclusive, the answer
is that a human should look, not that nobody should.

None of this changes MEDICAL REVIEW's rule-based verdict. The Tribunal informs
the human; it never overrides the rule.
"""
from __future__ import annotations

import logging
from typing import Any

from tribunal.models import (Arbitration, CrossExamResponse, DiscardedClaim,
                             PersonaVerdict)

log = logging.getLogger("cureva.tribunal.round3")


def _claim_text(verdict: PersonaVerdict) -> str:
    cites = ", ".join(f"{e.domain}:{e.usubjid}:{e.seq}" for e in verdict.cited_evidence)
    return f"[{verdict.persona}] {verdict.verdict}: {verdict.reasoning} (cites {cites or 'nothing'})"


def arbitrate(atlas: Any, finding: Any, finding_id: str,
              round1: list[PersonaVerdict], round2: list[CrossExamResponse],
              cut: int | None) -> Arbitration:
    """Verify every claim and derive the verdict from whatever survives."""
    surviving: list[str] = []
    discarded: list[DiscardedClaim] = []
    standing: dict[str, str] = {}      # persona -> its surviving verdict

    # ---------------------------------------------------- Round 1 claims
    for verdict in round1:
        text = _claim_text(verdict)

        if not verdict.cited_evidence:
            discarded.append(DiscardedClaim(
                persona=verdict.persona, claim=text,
                reason_discarded="cited no evidence at all, so there is nothing "
                                 "an evidence check can confirm"))
            continue

        bad: list[str] = []
        for ref in verdict.cited_evidence:
            if not atlas.verify_evidence(ref, verdict.reasoning,
                                         code=finding.code, cut=cut):
                bad.append(f"{ref.domain}:{ref.usubjid}:{ref.seq}")

        if bad:
            discarded.append(DiscardedClaim(
                persona=verdict.persona, claim=text,
                reason_discarded=(
                    f"cited {', '.join(bad)}, which the {finding.code} detector "
                    f"does not cite for this subject at cut {cut} — the record "
                    f"either does not exist, is not visible at this cut, or does "
                    f"not support the claim")))
            continue

        surviving.append(text)
        standing[verdict.persona] = verdict.verdict

    # ---------------------------------------------------- Round 2 claims
    made_a_claim = {v.persona for v in round1}
    for response in round2:
        for challenge in response.challenges:
            text = (f"[{response.persona} -> {challenge.target_persona}] "
                    f"challenged: {challenge.claim_challenged} | "
                    f"rebuttal: {challenge.rebuttal}")
            if challenge.target_persona not in made_a_claim:
                discarded.append(DiscardedClaim(
                    persona=response.persona, claim=text,
                    reason_discarded=(f"challenges {challenge.target_persona}, which "
                                      f"produced no Round 1 verdict to challenge")))
                continue
            surviving.append(text)

        # A revision only counts if the persona is still standing -- a persona
        # whose own evidence was discarded does not get to move the verdict.
        if response.revised_verdict and response.persona in standing:
            standing[response.persona] = response.revised_verdict
            surviving.append(f"[{response.persona}] revised its verdict to "
                             f"{response.revised_verdict} after cross-examination")

    # ------------------------------------------------------ final verdict
    votes = list(standing.values())
    escalate = sum(1 for v in votes if v == "ESCALATE")
    monitor = sum(1 for v in votes if v == "MONITOR")
    final = "MONITOR" if monitor > escalate else "ESCALATE"

    log.debug("round 3 for %s: %d surviving, %d discarded, votes E=%d M=%d",
              finding_id, len(surviving), len(discarded), escalate, monitor)

    return Arbitration(finding_id=finding_id, surviving_claims=surviving,
                       discarded_claims=discarded, final_verdict=final)
