"""T1.33 — the clinical layer: red-flag screening, patient context, TTS locale.

Deterministic, no network, no credentials. These are the behaviours that must
hold on demo day regardless of what the language model decides to say.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []
def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

from intake.red_flags import screen, escalation_sentence
from intake.sarvam_client import supported_language, SUPPORTED_TTS_LANGUAGES
from intake.patient_context import build as build_context
from stage1.atlas import StudyGraph

print("=== red flags fire on reportable symptoms, however they are worded ===")
MUST_FLAG = [
    ("I've had chest pain since this morning", "possible cardiac event"),
    ("I'm short of breath", "respiratory compromise"),
    ("my eyes look yellow", "possible jaundice — liver safety"),
    ("My eyes have been looking a bit yellow for two days", "possible jaundice — liver safety"),
    ("the whites of my eyes are going yellow", "possible jaundice — liver safety"),
    ("my skin has a yellow tinge", "possible jaundice — liver safety"),
    ("my urine has been very dark", "possible liver or renal involvement"),
    ("I fainted yesterday", "syncope"),
    ("I ended up in hospital", "possible hospitalisation — serious by protocol §6"),
    ("I've been vomiting blood", "gastrointestinal bleeding"),
]
for text, reason in MUST_FLAG:
    reasons = [h["reason"] for h in screen(text)]
    check(f"{text[:44]!r:46} -> {reason.split('—')[0].strip()}",
          reason in reasons, f"got {reasons}")

print("\n=== and stay quiet on ordinary reports (no crying wolf) ===")
MUST_NOT_FLAG = [
    "I've had a mild headache since yesterday",
    "I'm taking ibuprofen for it",
    "I feel a bit tired in the afternoons",
    "my appetite has been lower",
    "What time is my next appointment?",
    "I have a yellow folder with my study paperwork",
]
for text in MUST_NOT_FLAG:
    hits = screen(text)
    check(f"{text[:44]!r:46} -> no flag", not hits, str([h["reason"] for h in hits]))

print("\n=== the escalation sentence names why, and never diagnoses ===")
sentence = escalation_sentence(screen("chest pain and short of breath"))
print(f"  {sentence.strip()}")
check("tells the patient it is being flagged", "flagging this" in sentence)
check("directs them to the study doctor", "study doctor" in sentence)
check("names the reason", "cardiac" in sentence)
check("no flags -> no sentence", escalation_sentence([]) == "")
for banned in ("you have", "diagnos", "stop taking", "it is likely"):
    check(f"never says {banned!r}", banned not in sentence.lower())

print("\n=== screening looks at the model's normalised term too ===")
# The model often rewrites "my eyes look yellow" to the term "jaundice"; the
# screen must catch it from either side.
check("a normalised term alone still flags",
      any("jaundice" in h["reason"] for h in screen("I don't feel right", "jaundice")))

print("\n=== TTS language is coerced into what Sarvam actually accepts ===")
# Groq returns en-US/en-GB in practice despite being asked for a BCP-47 tag,
# and bulbul rejects anything outside its own list with HTTP 400.
for given, expected in [("en-IN", "en-IN"), ("en-US", "en-IN"), ("en-GB", "en-IN"),
                        ("en", "en-IN"), ("hi", "hi-IN"), ("hi-IN", "hi-IN"),
                        ("ta", "ta-IN"), ("pt-BR", "en-IN"), ("zz-ZZ", "en-IN"),
                        (None, "en-IN"), ("", "en-IN")]:
    check(f"{str(given):8} -> {expected}", supported_language(given) == expected,
          f"got {supported_language(given)}")
check("every coerced value is one Sarvam accepts",
      all(supported_language(x) in SUPPORTED_TTS_LANGUAGES
          for x in ["en-US", "fr-FR", None, "", "zz", "hi"]))

print("\n=== the patient briefing is real, specific, and unit-correct ===")
g = StudyGraph("hackathon-data"); g.build(cut=None)
ctx = build_context(g, "042-S07-001")
print("  " + ctx.replace("\n", "\n  ")[:420] + "…")
check("names the subject", "042-S07-001" in ctx)
check("states their arm", "PLACEBO" in ctx)
check("lists their real concomitant medications", "Glibenclamide" in ctx)
check("reports the unit-CONVERTED ALT, not the raw number",
      "239.7 U/L" in ctx, "must not show the raw 3.995 as if it were U/L")
check("shows the raw value and that it was converted",
      "3.995 ukat/L" in ctx and "converted" in ctx)
check("includes the bilirubin that makes it Hy's law", "BILI 5.38" in ctx)
check("mentions their real adverse event", "Diarrhoea" in ctx)

print("\n=== a subject not in the study gets no invented briefing ===")
check("unknown subject -> empty context, nothing fabricated",
      build_context(g, "NOT-A-REAL-SUBJECT") == "")

print("\n=== a subject with no conmeds says so rather than omitting it ===")
sparse = build_context(g, "042-S05-021")      # the duplicate-enrolment subject
check("absence is stated explicitly",
      "No concomitant medications" in sparse or "No adverse events" in sparse,
      sparse[:160])

print("\n" + ("ALL T1.33 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
