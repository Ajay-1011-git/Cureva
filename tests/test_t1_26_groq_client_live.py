"""T1.26 VERIFY — real Groq call, dual-output extraction."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
           override=True)
from intake.groq_client import GroqAvatarClient, GroqUnavailable
from intake.models import AvatarTurnResponse

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

try:
    client = GroqAvatarClient()
except GroqUnavailable:
    print("SKIP: no Groq key configured — nothing to verify live.")
    sys.exit(0)

print("=== VERIFY (required): symptom + conmed mention, real call ===")
utterance = "I've had a headache since yesterday and I'm also taking ibuprofen for it"
resp = client.turn(utterance)
print(json.dumps(resp.model_dump(mode="json"), indent=2))

check("returns a validated AvatarTurnResponse", isinstance(resp, AvatarTurnResponse))
check("reply_text is non-empty", len(resp.reply_text) > 0)
check("reply_lang is a real BCP-47 tag with a region subtag", "-" in resp.reply_lang)
check("gesture is one of the closed six-tag set",
      resp.gesture in ("idle", "listening", "concern_lean_in", "explaining_gesture",
                       "reassure_nod", "farewell_wave"))
check("extracted BOTH the symptom and the conmed mention", len(resp.extracted) == 2)

symptom = next((e for e in resp.extracted if e.pro_type == "SYMPTOM"), None)
conmed = next((e for e in resp.extracted if e.pro_type == "CONMED_MENTION"), None)
check("a SYMPTOM extraction is present", symptom is not None)
check("a CONMED_MENTION extraction is present", conmed is not None)
if symptom:
    print(f"\n  symptom: term={symptom.term!r} raw_quote={symptom.raw_quote!r}")
    check("symptom term names the headache", "headache" in symptom.term.lower())
    check("symptom raw_quote is a verbatim substring of the input",
          symptom.raw_quote in utterance)
if conmed:
    print(f"  conmed : term={conmed.term!r} raw_quote={conmed.raw_quote!r}")
    check("conmed term names ibuprofen", "ibuprofen" in conmed.term.lower())
    check("conmed raw_quote is a verbatim substring of the input",
          conmed.raw_quote in utterance)

print("\n=== VERIFY: gesture selection is contextually sensible across utterances ===")
cases = [
    ("Hello, I'm feeling fine today, just checking in.", None),
    ("I'm really scared, my chest has been hurting badly since this morning.", "concern_lean_in"),
    ("Thank you so much for your help, goodbye.", "farewell_wave"),
]
for text, expected in cases:
    r = client.turn(text)
    print(f"  {text[:50]!r:52} -> gesture={r.gesture!r}")
    if expected:
        check(f"{text[:30]!r} produces {expected!r}", r.gesture == expected)
    check(f"gesture is always from the closed set",
          r.gesture in ("idle", "listening", "concern_lean_in", "explaining_gesture",
                       "reassure_nod", "farewell_wave"))

print("\n=== VERIFY: no fabricated date from relative language (fixed during this task) ===")
r2 = client.turn(utterance)
dates = [e.reported_date for e in r2.extracted]
print(f"  reported_date values for 'since yesterday': {dates}")
check("no hallucinated absolute date inferred from relative language ('yesterday')",
      all(d is None for d in dates))

print("\n=== VERIFY: an utterance with nothing to extract yields an empty list ===")
r3 = client.turn("What time is my next appointment?")
print(f"  'What time is my next appointment?' -> extracted={r3.extracted}")
check("no symptom/conmed -> empty extraction, nothing invented", r3.extracted == [])

print("\n=== VERIFY (required, FR-18): out-of-enum gesture coerces to idle, IN PLACE ===")
from intake.models import AvatarTurnResponse as ATR
try:
    ATR.model_validate({"reply_text": "x", "reply_lang": "en-IN",
                        "gesture": "not_a_real_gesture", "extracted": []})
    check("pydantic itself rejects an out-of-enum gesture at the schema level", False)
except Exception:
    check("pydantic itself rejects an out-of-enum gesture at the schema level", True)

# Now the actual client behaviour: simulate Groq returning a bad gesture tag
# alongside an otherwise-perfectly-good response, and confirm the CLIENT
# coerces just that field rather than discarding the whole response.
import json as _json
from unittest.mock import patch, MagicMock

bad_payload = _json.dumps({
    "reply_text": "This reply text must survive the coercion.",
    "reply_lang": "en-IN",
    "gesture": "waving_dramatically",   # not in the closed set
    "extracted": [{"pro_type": "SYMPTOM", "term": "fever",
                   "raw_quote": "I have a fever", "reported_date": None}],
})
mock_choice = MagicMock()
mock_choice.message.content = bad_payload
mock_completion = MagicMock()
mock_completion.choices = [mock_choice]

with patch.object(client._client.chat.completions, "create", return_value=mock_completion):
    coerced = client.turn("I have a fever")
print(f"  simulated bad gesture 'waving_dramatically' -> client returned gesture={coerced.gesture!r}")
print(f"  reply_text preserved: {coerced.reply_text!r}")
print(f"  extraction preserved: {[e.term for e in coerced.extracted]}")
check("out-of-enum gesture coerced to 'idle'", coerced.gesture == "idle")
check("the rest of the response (reply_text) is NOT discarded", "must survive" in coerced.reply_text)
check("the rest of the response (extraction) is NOT discarded", coerced.extracted[0].term == "fever")

print("\n" + ("ALL T1.26 LIVE CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
