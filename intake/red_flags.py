"""Deterministic red-flag detection over what a patient just said.

Act 1 only; never imported by stage1/atlas.py.

Why this is not left to the language model: the model DOES usually escalate a
red-flag symptom when the prompt asks it to, but "usually" is the wrong
reliability for the one behaviour where a miss matters. Observed directly
during testing — the same chest-pain-and-breathlessness sentence escalated on
one call and came back as an ordinary follow-up question on the next. A rule
that always fires is worth more here than a model that mostly does, so the
model's reply is treated as the bedside manner and this is treated as the
safety net. They run independently; either one firing raises the flag.

This is NOT a diagnosis and does not claim to be. It is a keyword screen for
symptoms that protocol §6 would call reportable, matching the same standard a
site coordinator is trained to escalate on.
"""
from __future__ import annotations

import re

#: Term -> why it is reportable. Kept as plain language because it is shown
#: to a human, not consumed by another system.
RED_FLAGS: dict[str, str] = {
    "chest pain": "possible cardiac event",
    "chest tightness": "possible cardiac event",
    "short of breath": "respiratory compromise",
    "shortness of breath": "respiratory compromise",
    "trouble breathing": "respiratory compromise",
    "difficulty breathing": "respiratory compromise",
    "can't breathe": "respiratory compromise",
    "cannot breathe": "respiratory compromise",
    "fainted": "syncope",
    "fainting": "syncope",
    "passed out": "syncope",
    "blacked out": "syncope",
    "jaundice": "possible jaundice — liver safety",
    "jaundiced": "possible jaundice — liver safety",
    "dark urine": "possible liver or renal involvement",
    "severe abdominal pain": "possible hepatobiliary event",
    "vomiting blood": "gastrointestinal bleeding",
    "blood in stool": "gastrointestinal bleeding",
    "bleeding": "possible haemorrhage",
    "blistering": "possible severe cutaneous reaction",
    "rash all over": "possible severe cutaneous reaction",
    "swelling of the face": "possible angioedema",
    "swollen face": "possible angioedema",
    "throat closing": "possible anaphylaxis",
    "seizure": "neurological event",
    "suicidal": "psychiatric emergency",
    "hurt myself": "psychiatric emergency",
    "end my life": "psychiatric emergency",
    "hospital": "possible hospitalisation — serious by protocol §6",
    "admitted": "possible hospitalisation — serious by protocol §6",
    "emergency room": "possible hospitalisation — serious by protocol §6",
    "a and e": "possible hospitalisation — serious by protocol §6",
}


#: Some symptoms are described too many ways to enumerate. Jaundice is the
#: clearest case — "yellow eyes", "eyes look yellow", "eyes have been looking
#: a bit yellow", "whites of my eyes are going yellow" all mean the same thing
#: and an exact-phrase list misses most of them. These pair a body part with a
#: colour within a short window of words instead, which is far more robust
#: than guessing at wordings. Liver safety is exactly where a miss is worst,
#: so it gets the more careful rule.
PROXIMITY_FLAGS: list[tuple[str, str, int, str]] = [
    (r"eyes?|whites?|skin|complexion", r"yellow(?:ing|ish)?|jaundiced?",
     8, "possible jaundice — liver safety"),
    (r"urine|pee|wee", r"dark|brown|tea[- ]colou?red",
     6, "possible liver or renal involvement"),
]


def _proximity_hits(haystack: str) -> list[dict]:
    hits = []
    for left, right, window, reason in PROXIMITY_FLAGS:
        # either order — "yellow eyes" and "eyes are yellow" both count
        pattern = (rf"\b(?:{left})\b(?:\W+\w+){{0,{window}}}?\W+\b(?:{right})\b"
                   rf"|\b(?:{right})\b(?:\W+\w+){{0,{window}}}?\W+\b(?:{left})\b")
        m = re.search(pattern, haystack)
        if m:
            hits.append({"term": " ".join(m.group(0).split()), "reason": reason})
    return hits


def screen(*texts: str | None) -> list[dict]:
    """Every red flag present across the given texts.

    Pass both what the patient said and the normalised terms extracted from
    it: a phrase the model rewrote ("jaundice" for "my eyes look yellow")
    should still be caught, and so should one it dropped entirely.

    Matching is word-boundary anchored so "bleeding" does not fire on
    "unbleeding" and "hospital" does not fire inside a longer unrelated word.
    """
    haystack = " ".join(t.lower() for t in texts if t)
    hits: list[dict] = _proximity_hits(haystack)
    seen: set[str] = {h["reason"] for h in hits}
    for term, reason in RED_FLAGS.items():
        if reason in seen:
            continue                     # one hit per reason is enough
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            hits.append({"term": term, "reason": reason})
            seen.add(reason)
    return hits


def escalation_sentence(hits: list[dict]) -> str:
    """The line appended to the avatar's reply when a red flag fires."""
    if not hits:
        return ""
    reasons = ", ".join(h["reason"] for h in hits)
    return (" I'm flagging this for your study doctor to review now — "
            f"({reasons}). Please contact the site today, and seek urgent care "
            "if it worsens.")
