"""Round 2 — cross-examination.

Each persona now sees the other two's real Round-1 reasoning and cited
evidence, verbatim, and is asked to challenge specific claims rather than to
express general disagreement. "I take a different view" is worthless to Round
3; "SAFETY's claim that LB:...:31 shows a post-baseline rise is not supported,
because that record is the baseline draw" is a claim that can be checked.

A persona may also revise its own verdict here. That is a real outcome, not a
failure -- a reviewer who reads two colleagues and changes their mind is what
a deliberation is for. What it may not do is revise toward consensus without
saying which specific claim moved it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from tribunal.client import ask_json, evidence_block, is_rate_limit
from tribunal.models import CrossExamResponse, PERSONAS, Persona, PersonaVerdict
from tribunal.round1 import PERSONA_BRIEF

log = logging.getLogger("cureva.tribunal.round2")

SCHEMA_INSTRUCTION = """
Answer with a single JSON object and nothing else:

{
  "challenges": [
    {"target_persona": "SAFETY" | "CLINICAL_OPS" | "REGULATORY",
     "claim_challenged": "the specific claim you are disputing, quoted or closely paraphrased",
     "rebuttal": "why the evidence does not support it"}
  ],
  "revised_verdict": "ESCALATE" or "MONITOR" or null
}

Rules you must follow:
- Challenge specific claims, not general positions. Quote or closely paraphrase
  the words you are disputing. A challenge that does not name something the
  other reviewer actually said is worthless to the adjudication.
- If another reviewer reached a different verdict from yours, you MUST challenge
  the specific reasoning that got them there. Silent disagreement is not a
  position; it is an abstention.
- If you agree with a reviewer's verdict but not their reasoning, challenge the
  reasoning. Agreeing for the wrong reason is still a defect in the record.
- Argue from your own discipline. Do not concede a point that falls squarely in
  your remit just because two others pushed back.
- "target_persona" must be one of the two other reviewers shown to you, never
  yourself.
- Set "revised_verdict" only if another reviewer's point actually changed your
  mind, and only when you have said which point did it; otherwise return null.
"""

STRICTER = "\n\nYour previous reply was not valid JSON matching the schema. Return ONLY the JSON object, no prose, no markdown fences."


def _others_block(persona: Persona, round1: list[PersonaVerdict]) -> str:
    """The other two personas' real Round-1 output, verbatim."""
    parts: list[str] = []
    for verdict in round1:
        if verdict.persona == persona:
            continue
        cites = ", ".join(f"{e.domain}:{e.usubjid}:{e.seq}" for e in verdict.cited_evidence)
        parts.append(f"--- {verdict.persona} said ---\n"
                     f"Verdict: {verdict.verdict}\n"
                     f"Reasoning: {verdict.reasoning}\n"
                     f"Evidence cited: {cites or '(none)'}")
    return "\n\n".join(parts) or "(no other reviewer produced a verdict)"


async def _one_persona(client: Any, persona: Persona, finding: Any, finding_id: str,
                       round1: list[PersonaVerdict], graph: Any,
                       cut: int | None) -> tuple[CrossExamResponse | None, int]:
    mine = next((v for v in round1 if v.persona == persona), None)
    disagreeing = [v.persona for v in round1
                   if mine is not None and v.persona != persona
                   and v.verdict != mine.verdict]
    pressure = ""
    if disagreeing:
        pressure = (f"\n\n{' and '.join(disagreeing)} reached a DIFFERENT verdict "
                    f"from yours. You must engage with their actual reasoning — "
                    f"say precisely where it fails on the evidence, or say what "
                    f"in it has changed your mind.")
    system = (f"{PERSONA_BRIEF[persona]}\n\nTwo other reviewers have independently "
              f"assessed the same finding. Read what they actually wrote and "
              f"cross-examine it.{pressure}{SCHEMA_INSTRUCTION}")
    user = (
        f"FINDING CODE: {finding.code}\n"
        f"SUBJECT: {finding.usubjid or '(site-level)'}\n"
        f"DATA CUT: {cut}\n\n"
        f"WHAT THE DETECTOR REPORTED:\n{finding.rationale}\n\n"
        f"THE EVIDENCE (real records, values at this cut):\n"
        f"{evidence_block(finding, graph, cut)}\n\n"
        f"YOUR OWN EARLIER VERDICT:\n"
        + (f"{mine.verdict} - {mine.reasoning}" if mine else "(you did not produce one)")
        + f"\n\nTHE OTHER REVIEWERS:\n{_others_block(persona, round1)}\n\n"
        f"Cross-examine them."
    )

    tokens = 0
    for attempt in range(2):
        prompt = system if attempt == 0 else system + STRICTER
        try:
            content, used = await ask_json(client, prompt, user)
            tokens += used
        except Exception as exc:                                  # noqa: BLE001
            if is_rate_limit(exc):
                log.warning("round 2 %s rate-limited", persona)
                return None, tokens
            log.warning("round 2 %s call failed: %s: %s", persona, type(exc).__name__, exc)
            continue
        if not content:
            continue
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            continue
        raw["persona"] = persona
        raw["finding_id"] = finding_id
        # A persona that names itself as the target of its own challenge is
        # dropping a malformed claim, not making one; remove those rather than
        # failing the whole response over it.
        raw["challenges"] = [c for c in (raw.get("challenges") or [])
                             if isinstance(c, dict) and c.get("target_persona") != persona]
        try:
            return CrossExamResponse.model_validate(raw), tokens
        except ValidationError as exc:
            log.debug("round 2 %s failed validation: %s", persona, exc)
            continue
    log.warning("round 2 %s produced no valid response", persona)
    return None, tokens


async def run_round2(client: Any, finding: Any, finding_id: str,
                     round1: list[PersonaVerdict], graph: Any,
                     cut: int | None) -> tuple[list[CrossExamResponse], int]:
    """Three concurrent cross-examinations. Returns (responses, tokens_used)."""
    if not round1:
        return [], 0
    present = [v.persona for v in round1]
    results = await asyncio.gather(
        *(_one_persona(client, p, finding, finding_id, round1, graph, cut)
          for p in PERSONAS if p in present),
        return_exceptions=True,
    )
    out: list[CrossExamResponse] = []
    tokens = 0
    for item in results:
        if isinstance(item, BaseException):
            log.warning("round 2 persona raised: %s", item)
            continue
        response, used = item
        tokens += used
        if response is not None:
            out.append(response)
    return out, tokens
