"""T1.26 CONTRACT — the Groq client's guarantees, deterministic and mocked.

This file replaces the gating half of the old `test_t1_26_groq_client_live.py`.

Why it was split: the old test asserted on what a live LLM actually said —
which gesture it picked for an ambiguous utterance, whether it extracted two
items or one. Those are the model's judgment calls, not this system's
contract, and asserting on them made the whole suite fail intermittently for
reasons that were never bugs (model variance, and Groq's 30 req/min free-tier
limit tripping when the full suite ran back to back).

What IS a contract, and is checked here with mocks so it can never flake:
  - a valid response is parsed and returned as an AvatarTurnResponse
  - an out-of-enum gesture is coerced to "idle" IN PLACE (PRD FR-18), keeping
    the rest of the response rather than discarding it
  - malformed JSON is retried once, then falls back — never raises
  - an unreachable Groq degrades to the keyword fallback (TRD §8), never a crash
  - a bare ISO-639 reply_lang is widened to a BCP-47 tag
  - the prompt actually forbids inventing a date from relative language

The live behaviour of the real model is exercised by `probes/probe_groq_live.py`,
which reports what it sees and never gates the build.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intake.groq_client import (GroqAvatarClient, GroqUnavailable, SYSTEM_PROMPT,
                                _keyword_fallback, _normalise_lang)
from intake.models import AvatarTurnResponse, PROExtraction

fails = []
def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def make_client():
    """A client with a dummy key — no network is ever touched in this file."""
    return GroqAvatarClient(api_key="test-key-not-used")


def mock_completion(content):
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


GOOD = json.dumps({
    "reply_text": "I'm sorry to hear that.",
    "reply_lang": "en-IN",
    "gesture": "concern_lean_in",
    "extracted": [{"pro_type": "SYMPTOM", "term": "headache",
                   "raw_quote": "I have a headache", "reported_date": None}],
})

client = make_client()

print("=== a well-formed response is parsed and returned ===")
with patch.object(client._client.chat.completions, "create",
                  return_value=mock_completion(GOOD)):
    r = client.turn("I have a headache")
print(f"  {r.model_dump()}")
check("returns an AvatarTurnResponse", isinstance(r, AvatarTurnResponse))
check("reply_text preserved", r.reply_text == "I'm sorry to hear that.")
check("gesture preserved", r.gesture == "concern_lean_in")
check("extraction preserved", len(r.extracted) == 1 and r.extracted[0].term == "headache")

print("\n=== FR-18: an out-of-enum gesture coerces to idle, keeping everything else ===")
bad_gesture = json.dumps({
    "reply_text": "This must survive.", "reply_lang": "en-IN",
    "gesture": "waving_dramatically",
    "extracted": [{"pro_type": "SYMPTOM", "term": "fever",
                   "raw_quote": "I have a fever", "reported_date": None}],
})
with patch.object(client._client.chat.completions, "create",
                  return_value=mock_completion(bad_gesture)):
    r = client.turn("I have a fever")
print(f"  gesture={r.gesture!r} reply_text={r.reply_text!r} extracted={[e.term for e in r.extracted]}")
check("out-of-enum gesture coerced to 'idle'", r.gesture == "idle")
check("reply_text NOT discarded", "must survive" in r.reply_text)
check("extraction NOT discarded", r.extracted and r.extracted[0].term == "fever")
try:
    AvatarTurnResponse.model_validate({"reply_text": "x", "reply_lang": "en-IN",
                                       "gesture": "waving_dramatically", "extracted": []})
    schema_rejects = False
except Exception:
    schema_rejects = True
check("pydantic rejects that gesture at the schema level, so the coercion above "
      "is load-bearing and not cosmetic", schema_rejects)

print("\n=== every one of the six valid gestures passes through untouched ===")
for gesture in ("idle", "listening", "concern_lean_in", "explaining_gesture",
                "reassure_nod", "farewell_wave"):
    payload = json.dumps({"reply_text": "x", "reply_lang": "en-IN",
                          "gesture": gesture, "extracted": []})
    with patch.object(client._client.chat.completions, "create",
                      return_value=mock_completion(payload)):
        r = client.turn("x")
    check(f"{gesture} survives coercion", r.gesture == gesture)

print("\n=== malformed JSON: retried once, then falls back — never raises ===")
create = MagicMock(return_value=mock_completion("this is not json at all"))
with patch.object(client._client.chat.completions, "create", create):
    r = client.turn("hello")
print(f"  after 2 bad attempts -> {r.model_dump()}")
check("returned a valid AvatarTurnResponse rather than raising",
      isinstance(r, AvatarTurnResponse))
check("retried exactly twice before falling back", create.call_count == 2,
      f"call_count={create.call_count}")
check("fell back to the canned reply", r.reply_text == "Could you say that again?")
check("fallback invents no extraction", r.extracted == [])

print("\n=== a malformed FIRST attempt still succeeds if the retry is good ===")
create = MagicMock(side_effect=[mock_completion("{{ broken"), mock_completion(GOOD)])
with patch.object(client._client.chat.completions, "create", create):
    r = client.turn("I have a headache")
check("the retry's good response is used", r.gesture == "concern_lean_in")
check("exactly two calls were made", create.call_count == 2)

print("\n=== empty content (the reasoning_effort failure mode) is retried, not returned ===")
create = MagicMock(side_effect=[mock_completion(""), mock_completion(GOOD)])
with patch.object(client._client.chat.completions, "create", create):
    r = client.turn("I have a headache")
check("empty content triggers a retry rather than an empty reply",
      r.reply_text == "I'm sorry to hear that.")

print("\n=== Groq unreachable: degrades to the keyword fallback (TRD §8), never crashes ===")
create = MagicMock(side_effect=RuntimeError("connection refused"))
with patch.object(client._client.chat.completions, "create", create):
    r = client.turn("I've had a headache since yesterday")
print(f"  {r.model_dump()}")
check("returned a valid response despite the transport failing",
      isinstance(r, AvatarTurnResponse))
check("keyword fallback still captures the patient's own words verbatim",
      r.extracted and r.extracted[0].raw_quote == "I've had a headache since yesterday")
check("keyword fallback marks the extraction as OTHER, claiming no classification",
      r.extracted and r.extracted[0].pro_type == "OTHER")
check("gesture stays inside the closed set", r.gesture == "listening")

print("\n=== an empty message produces no invented extraction ===")
r = _keyword_fallback("")
check("empty input -> empty extraction", r.extracted == [])
r = _keyword_fallback("   ")
check("whitespace-only input -> empty extraction", r.extracted == [])

print("\n=== reply_lang: a bare ISO-639 code is widened to BCP-47 ===")
for bare, expected in (("en", "en-IN"), ("hi", "hi-IN"), ("ta", "ta-IN")):
    widened = _normalise_lang(AvatarTurnResponse(
        reply_text="x", reply_lang=bare, gesture="idle", extracted=[]))
    check(f"{bare!r} -> {expected!r}", widened.reply_lang == expected,
          f"got {widened.reply_lang!r}")
already = _normalise_lang(AvatarTurnResponse(
    reply_text="x", reply_lang="pt-BR", gesture="idle", extracted=[]))
check("an already-regioned tag passes through untouched", already.reply_lang == "pt-BR")

print("\n=== the prompt forbids inventing a date from relative language ===")
check("system prompt tells the model it does not know today's date",
      "you do not reliably know today" in SYSTEM_PROMPT.lower())
check("system prompt requires a verbatim raw_quote",
      "verbatim" in SYSTEM_PROMPT.lower())
check("system prompt forbids inventing extractions",
      "never invent" in SYSTEM_PROMPT.lower())

print("\n=== a missing API key fails loudly at construction, not silently at call time ===")
saved = {k: os.environ.pop(k) for k in ("GROQ_API_KEY", "groq_api_key")
         if k in os.environ}
try:
    try:
        GroqAvatarClient()
        check("no key raises GroqUnavailable", False)
    except GroqUnavailable:
        check("no key raises GroqUnavailable", True)
finally:
    os.environ.update(saved)

print("\n" + ("ALL T1.26 CONTRACT CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
