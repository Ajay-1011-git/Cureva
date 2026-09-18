"""Groq dual-output client — one call produces AvatarTurnResponse.

Act 1 only, never imported by stage1/atlas.py. Shapes verified against
console.groq.com live on this build session (anti-hallucination rule 2):
model IDs "openai/gpt-oss-20b"/"openai/gpt-oss-120b" confirmed current;
reasoning_effort accepts "low"/"medium"/"high"; when JSON mode is in use,
reasoning_format must be set to "parsed" or "hidden" (confirmed — a
requirement the build instructions' own §B.4 did not mention, added here).

Setting reasoning_effort explicitly is the documented mitigation for this
model family's known failure mode — content returning empty when it is
omitted, already hit once on a prior project (the Setu/Gestura repo this
avatar harness is reused from) per cureva-architecture.md's own tech-stack
table. Kept as a hard requirement here regardless of what the current docs
do or don't say about it, since the cost of setting it is zero and the cost
of hitting that failure mode live is a dead avatar.
"""
from __future__ import annotations

import json
import os

from groq import Groq
from pydantic import ValidationError

from .models import AvatarTurnResponse

MODEL = "openai/gpt-oss-20b"          # fast/cheap — avatar turns (per architecture doc)

SYSTEM_PROMPT = """You are Cureva's patient-intake avatar for a clinical trial. \
A patient is describing symptoms or medications to you, in any language.

Respond with a JSON object matching exactly this shape:
{
  "reply_text": "<your natural reply to the patient, in their own language>",
  "reply_lang": "<BCP-47 code matching reply_text's language, e.g. en-IN, hi-IN>",
  "gesture": "<exactly one of: idle, listening, concern_lean_in, explaining_gesture, reassure_nod, farewell_wave>",
  "extracted": [
    {"pro_type": "SYMPTOM" | "CONMED_MENTION" | "OTHER",
     "term": "<normalised term, e.g. 'headache', 'ibuprofen'>",
     "raw_quote": "<the patient's EXACT words for this, verbatim from their message>",
     "reported_date": "<YYYY-MM-DD ONLY if the patient stated an explicit calendar date; null for relative language like \'yesterday\' or \'since Monday\' -- you do not reliably know today\'s date, so never compute one>"}
  ]
}

Rules:
- reply_text should sound warm and human, not clinical. Keep it brief (1-3 sentences).
- gesture must be exactly one of the six listed values — nothing else.
- extracted should contain ONLY things the patient actually said. If they mentioned
  no symptom or medication, extracted must be an empty list []. Never invent an entry.
- raw_quote must be a verbatim substring of what the patient said — never paraphrased,
  never fabricated. An extraction without a real raw_quote from their own words is wrong.
- Output ONLY the JSON object. No markdown fences, no extra text."""

STRICT_REMINDER = "\n\nReturn ONLY valid JSON matching the exact schema above. No other text."


class GroqUnavailable(Exception):
    """The Groq call failed or its output could not be validated after a retry."""


def _fallback_response() -> AvatarTurnResponse:
    """TRD §8's degraded-but-alive path: a canned reply, no fabricated extraction."""
    return AvatarTurnResponse(
        reply_text="Could you say that again?", reply_lang="en-IN",
        gesture="idle", extracted=[])


def _keyword_fallback(patient_text: str) -> AvatarTurnResponse:
    """When Groq is unavailable entirely: a still-useful degraded path.

    TRD §8: "the raw text is still written as a PROExtraction with
    pro_type='OTHER' via a simple keyword pass, so a demo doesn't go visibly
    dead even if the dual-output call fails." A simple, honest pass — the
    raw_quote is always the patient's own text verbatim, never invented.
    """
    from .models import PROExtraction
    text = (patient_text or "").strip()
    extracted = [PROExtraction(pro_type="OTHER", term=text[:80], raw_quote=text,
                               reported_date=None)] if text else []
    return AvatarTurnResponse(
        reply_text="Thank you, let me note that down.", reply_lang="en-IN",
        gesture="listening", extracted=extracted)


class GroqAvatarClient:
    """One structured call per avatar turn: patient text -> AvatarTurnResponse."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("groq_api_key")
        if not key:
            raise GroqUnavailable("no Groq API key found — set GROQ_API_KEY in .env")
        self._client = Groq(api_key=key)

    def turn(self, patient_text: str, lang_hint: str | None = None) -> AvatarTurnResponse:
        """Patient's transcribed message -> a validated AvatarTurnResponse.

        Retries once on a schema-validation failure with a stricter reminder;
        falls back to a keyword-only extraction (never a crash) if Groq itself
        is unreachable, and to a plain canned reply if Groq answers but the
        second attempt still fails validation.
        """
        user_msg = patient_text if not lang_hint else f"[patient's language hint: {lang_hint}]\n{patient_text}"

        for attempt, prompt in enumerate((SYSTEM_PROMPT, SYSTEM_PROMPT + STRICT_REMINDER)):
            try:
                completion = self._client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": prompt},
                             {"role": "user", "content": user_msg}],
                    response_format={"type": "json_object"},
                    reasoning_effort="low",     # required — see module docstring
                    reasoning_format="hidden",  # required alongside JSON mode
                    temperature=0.4,
                )
            except Exception as exc:              # network/auth/rate-limit — Groq unreachable
                if attempt == 0:
                    continue                       # one retry might just be a blip
                return _keyword_fallback(patient_text)

            content = (completion.choices[0].message.content or "").strip()
            if not content:
                continue                            # empty content — retry once, then fall back

            try:
                raw = json.loads(content)
            except json.JSONDecodeError:
                continue                            # not JSON at all — retry once with the stricter prompt

            # An out-of-enum gesture is coerced to "idle" in place (PRD FR-18)
            # rather than treated as a validation failure that discards an
            # otherwise-good reply_text/extracted — the model got the content
            # right and only the gesture tag wrong, so only that is corrected.
            allowed_gestures = {"idle", "listening", "concern_lean_in",
                                "explaining_gesture", "reassure_nod", "farewell_wave"}
            if isinstance(raw, dict) and raw.get("gesture") not in allowed_gestures:
                raw["gesture"] = "idle"

            try:
                parsed = AvatarTurnResponse.model_validate(raw)
            except ValidationError:
                continue                            # some other field is wrong — retry once
            return _normalise_lang(parsed)

        return _fallback_response()


def _normalise_lang(response: AvatarTurnResponse) -> AvatarTurnResponse:
    """Widen a bare ISO-639 code ("en") to a BCP-47 tag ("en-IN") when the
    model omits the region subtag. Observed live: gpt-oss-20b reliably
    returns "en" rather than "en-IN" for English replies even though the
    system prompt asks for a full BCP-47 code — corrected here rather than
    re-prompting, since the language itself was identified correctly and
    only the tag's specificity was short."""
    lang = response.reply_lang or "en-IN"
    if "-" not in lang and len(lang) <= 3:
        # A conservative, common default per bare ISO-639 code seen in
        # practice; anything already region-tagged passes through untouched.
        widened = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN",
                  "kn": "kn-IN", "ml": "ml-IN", "bn": "bn-IN", "mr": "mr-IN",
                  "gu": "gu-IN", "pa": "pa-IN"}.get(lang.lower(), lang)
        response = response.model_copy(update={"reply_lang": widened})
    return response
