"""Live probe — what the real Groq model actually does, right now.

NOT a test. This never fails the build, and it is deliberately not in
`tests/`. Its job is to show you what the live model returns so you can
eyeball whether Act 1 is behaving sensibly before a demo, and to tell you
plainly when you have hit Groq's free-tier rate limit rather than pretending
that is a code defect.

The Groq client's actual guarantees — gesture coercion, retry-then-fallback,
keyword degradation, language widening — are contract-tested deterministically
with mocks in `tests/test_t1_26_groq_contract.py`, which does gate the build.
What the model *chooses to say* is not a contract and is not asserted here.

    python probes/probe_groq_live.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

from intake.groq_client import GroqAvatarClient, GroqUnavailable

VALID_GESTURES = {"idle", "listening", "concern_lean_in",
                  "explaining_gesture", "reassure_nod", "farewell_wave"}

#: The exact shape groq_client returns when every attempt failed. Seeing this
#: from a live probe almost always means the 30 req/min free-tier limit, not
#: a bug — the fallback firing IS the designed behaviour (TRD §8).
RATE_LIMITED = ("Could you say that again?", "idle", [])

OBSERVATIONS = []


def note(ok, label, detail=""):
    OBSERVATIONS.append(ok)
    mark = "ok  " if ok else "note"
    print(f"  [{mark}] {label}{('   ' + detail) if detail else ''}")


def main() -> int:
    try:
        client = GroqAvatarClient()
    except GroqUnavailable as exc:
        print(f"No Groq key configured ({exc}).")
        print("Nothing to probe. The client's contract is still fully covered by")
        print("tests/test_t1_26_groq_contract.py, which needs no key.")
        return 0

    print("Live Groq probe — reporting only, never gates the build")
    print("=" * 66)

    utterance = "I've had a headache since yesterday and I'm also taking ibuprofen for it"
    print(f"\nutterance: {utterance!r}")
    resp = client.turn(utterance)

    if (resp.reply_text, resp.gesture, resp.extracted) == RATE_LIMITED:
        print("\n  Got the fallback response — this is almost certainly Groq's")
        print("  free-tier rate limit (30 req/min), not a defect. The fallback")
        print("  firing cleanly is the behaviour TRD §8 asks for.")
        print("  Wait ~60s and re-run if you want a real sample.")
        print("=" * 66)
        return 0

    print(json.dumps(resp.model_dump(mode="json"), indent=2, default=str))
    print()
    note(bool(resp.reply_text), "reply_text is non-empty")
    note("-" in resp.reply_lang, f"reply_lang is a full BCP-47 tag", resp.reply_lang)
    note(resp.gesture in VALID_GESTURES, "gesture is inside the closed set", resp.gesture)

    kinds = {e.pro_type for e in resp.extracted}
    note("SYMPTOM" in kinds, "picked up the symptom mention")
    note("CONMED_MENTION" in kinds, "picked up the medication mention")
    for e in resp.extracted:
        verbatim = e.raw_quote in utterance
        note(verbatim, f"{e.pro_type} raw_quote is verbatim from the input",
             repr(e.raw_quote))
    note(all(e.reported_date is None for e in resp.extracted),
         "no absolute date invented from 'since yesterday'")

    print("\ngesture selection across different utterances")
    print("  (which gesture fits an ambiguous line is the model's judgment call —")
    print("   reported, not asserted)")
    for text in ("Hello, I'm feeling fine today, just checking in.",
                 "I'm really scared, my chest has been hurting badly since this morning.",
                 "Thank you so much for your help, goodbye."):
        r = client.turn(text)
        inside = r.gesture in VALID_GESTURES
        note(inside, f"{text[:46]!r:48} -> {r.gesture}")

    print("\n" + "=" * 66)
    if all(OBSERVATIONS):
        print("Everything the probe looked at behaved sensibly.")
    else:
        print(f"{OBSERVATIONS.count(False)} observation(s) worth a look above.")
        print("None of this gates the build — see tests/test_t1_26_groq_contract.py")
        print("for the guarantees that do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
