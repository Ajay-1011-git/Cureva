"""Round 1 — three personas, three independent verdicts, no cross-talk.

The isolation requirement is structural, not a polite instruction: each
persona's prompt is built alone and never contains the other two's names,
output, or any hint that another reviewer exists. A persona told "two
colleagues are also reviewing this" would start hedging toward a consensus
that has not happened yet, and Round 2's disagreement would be theatre.

Three calls go out concurrently via `asyncio.gather`. A persona whose response
fails schema validation twice is recorded as having no verdict this round --
never a fabricated one. Three personas that all fail produce an empty round,
which Round 3 then arbitrates over honestly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from tribunal.client import (ask_json, citable_block, context_block,
                             evidence_block, is_rate_limit)
from tribunal.models import PERSONAS, Persona, PersonaVerdict

log = logging.getLogger("cureva.tribunal.round1")

# Each persona is given a different question to be accountable for, which is
# what makes genuine disagreement possible. They are not three temperatures of
# the same reviewer.
PERSONA_BRIEF: dict[str, str] = {
    "SAFETY": (
        "You are the trial's safety physician, and you assess events the way a "
        "pharmacovigilance desk does.\n"
        "Your working frame: ICH E2A seriousness criteria (death, life-threatening, "
        "hospitalisation or its prolongation, persistent disability, congenital "
        "anomaly, or medically important). Seriousness is not severity — a mild "
        "event that causes admission is serious; a severe headache that does not is "
        "not. For hepatic signals you apply Hy's law properly: ALT or AST above 3x "
        "ULN together with total bilirubin above 2x ULN, in the absence of "
        "significant cholestasis (ALP below roughly 2x ULN), and you say so when "
        "ALP is not available to rule cholestasis out. You weigh temporal "
        "relationship to dosing, dose-response, and whether dechallenge or "
        "rechallenge information exists.\n"
        "Your only question is whether a participant may be being harmed and a "
        "clinician must act now. You are not responsible for data tidiness or "
        "paperwork. You would rather review ten events that turned out to be "
        "nothing than miss one that was something — but you say plainly when a "
        "finding is a data problem wearing a clinical costume."
    ),
    "CLINICAL_OPS": (
        "You are the clinical operations lead, and you assess findings the way a "
        "monitor preparing a site visit does.\n"
        "Your working frame: ICH E6(R2) Good Clinical Practice. You classify a "
        "deviation as major (affecting participant safety, data integrity, or "
        "their rights — reportable, needing corrective action) or minor "
        "(documented, trended, corrected locally). You distinguish an isolated "
        "clerical event from a systemic one: the questions you ask are whether it "
        "recurs, whether it clusters at one site or one coordinator, and whether "
        "source data would even support the value recorded. You think in terms of "
        "root cause and corrective action, not blame.\n"
        "Your only question is whether this reflects a site not running the "
        "protocol correctly, and at what scale. You are sceptical of escalating "
        "isolated data-entry noise, because a site that receives everything as an "
        "escalation stops reading escalations at all — and you say so even when "
        "the finding is real."
    ),
    "REGULATORY": (
        "You are the regulatory affairs reviewer, and you assess findings by asking "
        "what an inspector would make of the record as it stands.\n"
        "Your working frame: expedited reporting obligations for serious, "
        "unexpected, and reasonably drug-related events — 7 calendar days for fatal "
        "or life-threatening, 15 for other serious unexpected — and the "
        "documentation standards behind ALCOA+ (attributable, legible, "
        "contemporaneous, original, accurate, and complete, consistent, enduring, "
        "available). A duplicate enrolment, an eligibility breach, or a missing "
        "exposure record is a data-integrity matter whether or not anyone was "
        "harmed, because it undermines the analysis population and the audit "
        "trail.\n"
        "Your only question is whether an obligation is triggered and whether the "
        "record would survive inspection. You are explicit about which obligation "
        "you think applies, and equally explicit when none does — you do not "
        "inflate a tidy-up into a filing."
    ),
}

#: What each persona is asked to be concrete about, beyond the verdict. Stated
#: per-persona because a generic "explain yourself" produces generic prose, and
#: generic prose is exactly what makes a three-reviewer panel look like one
#: model answering three times.
PERSONA_FOCUS: dict[str, str] = {
    "SAFETY": ("State the seriousness criterion you are applying, or say plainly "
               "that none is met. If a hepatic signal is involved, say whether "
               "cholestasis can be excluded from the data you were given."),
    "CLINICAL_OPS": ("Classify this as a major or minor deviation and say which. "
                     "State whether the evidence supports an isolated event or a "
                     "pattern, and say if you cannot tell from one record."),
    "REGULATORY": ("Name the specific obligation you believe is or is not "
                   "triggered. If none is, say so — an absent obligation is a "
                   "finding too."),
}

SCHEMA_INSTRUCTION = """
Answer with a single JSON object and nothing else:

{
  "verdict": "ESCALATE" or "MONITOR",
  "reasoning": "three or four sentences in your own discipline's terms, citing the specific field values you relied on and naming the standard or criterion you applied",
  "cited_evidence": [ ... copied from CITABLE RECORDS below ... ]
}

Rules you must follow:
- "cited_evidence" may only contain entries copied EXACTLY from the CITABLE
  RECORDS list below, including each one's "seq" value as written there --
  including when it is null. Do not invent a record, a subject id or a
  sequence number, and do not substitute 0 for a missing sequence. If you rely
  on no specific record, return an empty list.
- Quote real field values in your reasoning. Do not restate the rationale you
  were given as though it were your own finding.
- ESCALATE means a human must make a decision about this now. MONITOR means it
  should be recorded and watched, but does not need a decision today.
- Reason from your own discipline. Do not hedge toward a middle position: state
  the call your role would actually make and what specifically would change it.
"""

STRICTER = "\n\nYour previous reply was not valid JSON matching the schema. Return ONLY the JSON object, no prose, no markdown fences."


def build_prompt(persona: Persona, finding: Any, graph: Any,
                 cut: int | None) -> tuple[str, str]:
    """(system, user) for one persona. Mentions no other persona, by design."""
    system = (f"{PERSONA_BRIEF[persona]}\n\nYou are reviewing one finding from an "
              f"ongoing clinical trial data review.\n\n"
              f"Be concrete about this: {PERSONA_FOCUS[persona]}"
              f"{SCHEMA_INSTRUCTION}")
    user = (
        f"FINDING CODE: {finding.code}\n"
        f"SUBJECT: {finding.usubjid or '(site-level)'}\n"
        f"SITE: {finding.site or '(unknown)'}\n"
        f"DATA CUT: {cut}\n"
        f"SEVERITY AS DETECTED: {finding.severity}\n\n"
        f"WHAT THE DETECTOR REPORTED:\n{finding.rationale}\n\n"
        f"THE EVIDENCE (real records, values as they stand at this cut):\n"
        f"{evidence_block(finding, graph, cut)}\n\n"
        f"{context_block(finding, graph, cut)}\n"
        f"CITABLE RECORDS (copy these verbatim into cited_evidence; nothing else "
        f"is citable):\n{citable_block(finding)}\n\n"
        f"Give your own verdict."
    )
    return system, user


async def _one_persona(client: Any, persona: Persona, finding: Any,
                       finding_id: str, graph: Any,
                       cut: int | None) -> tuple[PersonaVerdict | None, int, str | None]:
    system, user = build_prompt(persona, finding, graph, cut)
    tokens = 0
    reason: str | None = None
    for attempt in range(2):
        prompt = system if attempt == 0 else system + STRICTER
        try:
            content, used = await ask_json(client, prompt, user)
            tokens += used
        except Exception as exc:                                  # noqa: BLE001
            if is_rate_limit(exc):
                # Retrying now would spend the very window we are waiting on.
                log.warning("round 1 %s rate-limited", persona)
                return None, tokens, "Groq rate limit (tokens per minute) reached"
            reason = f"{type(exc).__name__}: {str(exc)[:120]}"
            log.warning("round 1 %s call failed: %s", persona, reason)
            continue
        if not content:
            continue
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            continue
        raw["persona"] = persona
        raw["finding_id"] = finding_id
        try:
            return PersonaVerdict.model_validate(raw), tokens, None
        except ValidationError as exc:
            reason = f"response failed schema validation: {str(exc)[:120]}"
            log.debug("round 1 %s failed validation: %s", persona, exc)
            continue
    # Two attempts, no valid verdict. That is recorded as silence, which
    # Round 3 can arbitrate over. It is never filled in with a guess.
    log.warning("round 1 %s produced no valid verdict", persona)
    return None, tokens, reason or "no valid response after two attempts"


async def run_round1(client: Any, finding: Any, finding_id: str, graph: Any,
                     cut: int | None) -> tuple[list[PersonaVerdict], int, list[str]]:
    """All three personas, concurrently.

    Returns (verdicts, tokens_used, reasons) -- `reasons` carries why any
    persona fell silent, so a skipped Tribunal can say what actually went
    wrong instead of only that nothing came back.
    """
    results = await asyncio.gather(
        *(_one_persona(client, p, finding, finding_id, graph, cut) for p in PERSONAS),
        return_exceptions=True,
    )
    verdicts: list[PersonaVerdict] = []
    reasons: list[str] = []
    tokens = 0
    for item in results:
        if isinstance(item, BaseException):
            log.warning("round 1 persona raised: %s", item)
            reasons.append(f"{type(item).__name__}: {str(item)[:120]}")
            continue
        verdict, used, reason = item
        tokens += used
        if verdict is not None:
            verdicts.append(verdict)
        elif reason:
            reasons.append(reason)
    return verdicts, tokens, reasons
