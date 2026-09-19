"""Act 5's optional polish pass — reword the prose, never touch a fact.

This is the single most droppable thing in the whole system, and it is built to
be dropped. The token ledger checks it *before* the call (FR-14), the model is
told it may only reword, and the result is verified against the template's own
facts before it is accepted. Any of those three failing ships the template
unchanged, tagged `template_only`, and the run continues.

**Why a fact check on the output at all?** Because "reword this and change no
numbers" is an instruction, and an instruction is not a guarantee. The template
already knows every fact it stated -- it built them from real records -- so
checking them back out of the polished text costs nothing and turns a hope into
a property. A polished draft that dropped or altered one cited value is
discarded in full rather than partly trusted.

The graded path never reaches this module: `run_period()` runs template-only by
default and needs no Groq key at all.
"""
from __future__ import annotations

import logging
import os
import re

from execute.templates import ExecutionArtifact
from stage3.budget import POLISH_ESTIMATED_TOKENS, TokenLedger

log = logging.getLogger("cureva.execute.polish")

#: The same model string the rest of this repository already uses. Not a second
#: model choice, and not a second key loader -- both are read the way
#: `intake/groq_client.py` reads them.
MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """You are copy-editing a clinical trial document.

Rewrite the document below so it reads more naturally for its stated audience.

ABSOLUTE CONSTRAINTS — breaking any of these makes your output unusable:
- Do NOT add, remove or alter any number, date, identifier, code, unit,
  measurement, subject id, site id, sequence number or field name.
- Do NOT add any fact, recommendation, conclusion, regulation, deadline or
  consequence that is not already written in the document.
- Do NOT remove any cited record line.
- Do NOT soften or strengthen what the document says happened.
- Keep every section heading.

You are changing sentences, not content. If you cannot improve a sentence
without touching a fact, leave it exactly as it is.

Return only the rewritten document. No preamble, no commentary."""

#: Identifier-shaped tokens, matched WHOLE. Order matters, and getting it
#: wrong leaves a hole: in the first version the bare-number rule came first,
#: so it consumed the leading "042-" of a subject id and left "S08" to the
#: code-token rule, which requires four characters and missed it. A polished
#: draft changing 042-S08-020 to 042-S99-020 would have passed. Compound ids
#: are matched first so they survive intact or are reported as altered.
#: A plain capitalised English word is NOT a fact. The first version matched
#: any ALL-CAPS token of four or more characters, which swept up every heading
#: word in the templates -- WHAT, FOUND, RECORDS, DECISION -- and made the
#: checker reject a draft for rewording a heading, which is a change of prose
#: and exactly what this pass exists to allow. Narrowed to the three shapes
#: that genuinely carry meaning:
#:   * compound identifiers      042-S08-020
#:   * short site/visit tokens   S08, S11
#:   * codes and field names     INCLUSION_VIOLATION (underscore or digit), or
#:                               any token used as a field: SITEID=, LBORRES=
_IDENTIFIER_PATTERN = re.compile(
    r"\b[A-Z0-9]{2,}-[A-Z0-9]+-[A-Z0-9]+\b"        # compound ids
    r"|\b[A-Z]{1,4}\d{1,3}\b"                      # short site/visit tokens
    r"|\b[A-Z][A-Z0-9]*[_0-9][A-Z0-9_]*\b"         # codes: have _ or a digit
    r"|\b[A-Z][A-Z0-9_]{2,}(?==)"                  # field names, used as KEY=
)

#: Bare numbers, taken from whatever the identifier pass did not claim.
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")

#: Dash variants a model will freely substitute. Normalised before comparing.
_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-",
                         "\u2013": "-", "\u2014": "-", "\u2212": "-"})


class PolishUnavailable(Exception):
    """Groq could not be reached or is not configured."""
class PolishUnavailable(Exception):
    """Groq could not be reached or is not configured."""


def _client():
    """The Groq client, using the existing key loader's own lookup order."""
    key = os.environ.get("GROQ_API_KEY") or os.environ.get("groq_api_key")
    if not key:
        raise PolishUnavailable("no Groq API key found")
    try:
        from groq import Groq
    except ImportError as exc:                                    # noqa: BLE001
        raise PolishUnavailable(f"groq SDK not installed: {exc}") from exc
    return Groq(api_key=key)


def facts_in(text: str) -> set[str]:
    """Every identifier and every numeric value stated in a piece of text.

    Two passes, and the split is what makes this usable rather than merely
    strict. Identifiers are compared WHOLE, because "042-S08-020" changing to
    "042-S99-020" is a different subject and must be caught. Numbers are
    compared as ATOMS, because "18-75" and "18 to 75" and "18–75" are the same
    range said three ways -- a real polish pass rewrites punctuation between
    numbers constantly, and rejecting that would reject every rewording while
    catching nothing real.

    Measured on the first real Groq call against this system: the model
    rewrote "18-75 inclusion range" with an en dash and the whole polish was
    discarded for "dropped: 18-75; invented: 18, 75". No fact had changed.
    Decomposing numbers fixes that without weakening the check -- AGE=17
    becoming AGE=18 still shows up as one number dropped and another invented.
    """
    normalised = (text or "").translate(_DASHES)
    identifiers = set(_IDENTIFIER_PATTERN.findall(normalised))
    # Blank out what the identifier pass claimed, so a subject id's own digits
    # are not also counted as loose numbers on one side and not the other.
    remainder = _IDENTIFIER_PATTERN.sub(" ", normalised)
    numbers = {n.replace(",", ".") for n in _NUMBER_PATTERN.findall(remainder)}
    return identifiers | numbers


def verify_facts_preserved(template_text: str,
                           polished_text: str) -> tuple[bool, list[str]]:
    """Whether the polished draft still states every fact the template did.

    One-directional on purpose. Facts that VANISHED are a failure: the polished
    draft would be quietly less true than the template. Facts that appeared are
    also a failure -- that is the model inventing a specific, which is the one
    thing this pass must never do. So the two sets must match exactly.
    """
    before, after = facts_in(template_text), facts_in(polished_text)
    lost = sorted(before - after)
    gained = sorted(after - before)
    problems = ([f"dropped: {', '.join(lost[:6])}"] if lost else []) + \
               ([f"invented: {', '.join(gained[:6])}"] if gained else [])
    return (not problems), problems


def polish_artifact(artifact: ExecutionArtifact, ledger: TokenLedger,
                    *, client=None,
                    estimated_tokens: int = POLISH_ESTIMATED_TOKENS
                    ) -> ExecutionArtifact:
    """Return a polished artifact, or the original unchanged.

    Four independent ways this returns the template untouched, and every one of
    them is a normal outcome rather than an error:

      1. the token ledger cannot afford the call -- and the call is then never
         attempted, so nothing is learned from a rate-limit error;
      2. Groq is unreachable, unconfigured, or raises;
      3. the response is empty or implausibly short;
      4. the polished text does not state exactly the facts the template did.

    The artifact is always returned. `source` is the honest record of which
    path was taken, and the UI renders the two differently (NFR-3).
    """
    # 1. Budget, checked BEFORE the call.
    if not ledger.can_afford(estimated_tokens):
        ledger.skip(f"Act 5 polish for {artifact.decision_id}", estimated_tokens)
        return artifact

    try:
        groq = client or _client()
        completion = groq.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": artifact.text}],
            reasoning_effort="low",   # required for this model family; see
                                      # intake/groq_client.py's module docstring
            temperature=0.2,
        )
        text = (completion.choices[0].message.content or "").strip()
        used = getattr(getattr(completion, "usage", None), "total_tokens", None)
    except Exception as exc:                                      # noqa: BLE001
        # 2. Unreachable. Never propagates: NFR-4 means no optional component
        # can take the graded path down with it.
        log.warning("polish unavailable for %s (%s: %s) - template ships",
                    artifact.decision_id, type(exc).__name__, exc)
        return artifact

    # The ledger is debited with the REAL count the provider reported, not the
    # estimate. The call happened and was paid for whatever the outcome below.
    ledger.debit(int(used) if used else estimated_tokens)

    # 3. Empty or truncated.
    if len(text) < len(artifact.text) * 0.5:
        log.warning("polish for %s came back implausibly short (%d vs %d chars) "
                    "- template ships", artifact.decision_id, len(text),
                    len(artifact.text))
        return artifact

    # 4. Facts must match exactly.
    ok, problems = verify_facts_preserved(artifact.text, text)
    if not ok:
        log.warning("polish for %s altered the facts (%s) - discarded in full, "
                    "template ships", artifact.decision_id, "; ".join(problems))
        return artifact

    return artifact.model_copy(update={"text": text, "source": "polished"})
