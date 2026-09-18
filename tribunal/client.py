"""The Tribunal's Groq transport.

Separate from `intake/groq_client.py` on purpose: that client is the avatar's,
bound to `AvatarTurnResponse` and the 20b model. This one is the Tribunal's,
bound to a persona schema and the 120b model. What is *shared* is the key
loading -- the same environment lookup, tolerant of both casings, rather than
a second differently-cased lookup that would silently find nothing.

Model and parameter discipline, re-verified live against Groq before this
module was written (build instructions, anti-hallucination rule 2):

* `openai/gpt-oss-120b` is still served. Confirmed against the live model
  list, not assumed from the Stage 1 build.
* `reasoning_effort` and `reasoning_format` are both still set on every call,
  but the reason has changed and the change is worth recording. Stage 1's
  ground truth says JSON mode returns *empty content* unless
  `reasoning_format` is set. That no longer reproduces: a JSON-mode call to
  120b with `reasoning_format` omitted now returns full content. Both fields
  are still sent -- `hidden` keeps the chain-of-thought out of the response
  body, which is what we want in a transcript a judge reads -- but the code no
  longer depends on a requirement that has since lapsed.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("cureva.tribunal.client")

#: Harder judgment than the avatar's 20b, per the architecture doc's split.
TRIBUNAL_MODEL = "openai/gpt-oss-120b"


class TribunalUnavailable(Exception):
    """No usable Groq key, or the Groq SDK is not installed."""


def load_key() -> str:
    """The same key Stage 1 already reads, looked up the same way."""
    key = os.environ.get("GROQ_API_KEY") or os.environ.get("groq_api_key")
    if not key:
        raise TribunalUnavailable("no Groq API key found (GROQ_API_KEY / groq_api_key)")
    return key


def make_client(api_key: str | None = None) -> Any:
    try:
        from groq import AsyncGroq
    except ImportError as exc:                                    # noqa: BLE001
        raise TribunalUnavailable(f"groq SDK not importable: {exc}") from exc
    return AsyncGroq(api_key=api_key or load_key())


async def ask_json(client: Any, system: str, user: str, *,
                   temperature: float = 0.3,
                   reasoning_effort: str = "low") -> tuple[str, int]:
    """One JSON-mode completion. Returns (content, tokens_used).

    Raises on transport failure; the caller decides what a failure means. This
    function deliberately does not retry -- the retry policy belongs with the
    schema validation in the round that knows what a valid answer looks like.
    """
    completion = await client.chat.completions.create(
        model=TRIBUNAL_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        reasoning_effort=reasoning_effort,
        reasoning_format="hidden",
        temperature=temperature,
    )
    content = (completion.choices[0].message.content or "").strip()
    tokens = getattr(getattr(completion, "usage", None), "total_tokens", 0) or 0
    return content, tokens


def is_rate_limit(exc: BaseException) -> bool:
    """Is this Groq telling us to slow down, rather than a real failure?

    Worth distinguishing everywhere it is caught. A rate limit means "correct
    request, come back later"; retrying it immediately just burns the window
    that the retry is waiting for. Matched on the message as well as the type,
    because the SDK's exception classes have moved before.
    """
    name = type(exc).__name__
    text = str(exc)
    return "RateLimit" in name or "429" in text or "rate_limit_exceeded" in text


def context_block(finding: Any, graph: Any, cut: int | None,
                  protocol_chars: int = 700) -> str:
    """The protocol text the finding rests on, plus the subject's own shape.

    A reviewer given only a rationale can do nothing but agree with it. Given
    the actual protocol clause and how much data the subject has, each persona
    can reach its own conclusion -- which is the only way three of them
    disagreeing means anything.

    Both halves are read from the graph, never summarised by a model, and the
    protocol excerpt is truncated hard: the free tier's ceiling is tokens per
    minute, so context that does not change a verdict is context that costs a
    deliberation.
    """
    parts: list[str] = []

    # The protocol section this finding actually cites.
    section_ref = next((e for e in finding.evidence if e.document and e.section), None)
    if section_ref is not None:
        try:
            from stage1.atlas import protocol_section
            text = (protocol_section(graph.document(section_ref.document),
                                     section_ref.section) or "").strip()
        except Exception:                                         # noqa: BLE001
            text = ""
        if text:
            if len(text) > protocol_chars:
                text = text[:protocol_chars].rstrip() + " […]"
            parts.append(f"THE PROTOCOL CLAUSE THIS RESTS ON "
                         f"({section_ref.document} §{section_ref.section}):\n{text}")

    # How much of a record this subject actually has, so "isolated or a
    # pattern" is answerable rather than guessable.
    if finding.usubjid:
        try:
            profile = graph.patient360(finding.usubjid)
            domains = profile.get("domains") or {}
            counts = ", ".join(f"{d}={len(v)}" for d, v in sorted(domains.items()) if v)
        except Exception:                                         # noqa: BLE001
            counts = ""
        if counts:
            parts.append(f"THIS SUBJECT'S RECORD AT CUT {cut}: {counts}")

    parts.append(f"PROTOCOL VERSION IN FORCE AT CUT {cut}: "
                 f"v{graph.protocol_version_at(cut)}")
    return "\n\n".join(parts)


def citable_block(finding: Any) -> str:
    """The finding's evidence as exact JSON objects a persona can copy.

    Rendering these separately from the human-readable evidence block fixes a
    real failure found while rehearsing: the schema example showed `"seq": 0`,
    so a persona citing a DM record -- a domain with no sequence column, whose
    records key at seq=null -- dutifully wrote 0, and Round 3 discarded every
    one of those claims as unsupported. They were correct claims. Giving the
    model the literal objects to copy removes the guess entirely.
    """
    import json as _json
    lines: list[str] = []
    for ref in finding.evidence:
        payload = {"domain": ref.domain, "usubjid": ref.usubjid, "seq": ref.seq}
        if ref.document:
            payload = {"domain": ref.domain, "document": ref.document,
                       "section": ref.section}
        lines.append("  " + _json.dumps(payload))
    return "\n".join(lines) or "  (none)"


def evidence_block(finding: Any, graph: Any, cut: int | None) -> str:
    """The finding's real records, rendered as fields rather than prose.

    Personas reason about actual values read out of the graph at this cut, not
    about a paraphrase of the rationale. A persona given only prose can only
    ever agree with the prose.
    """
    lines: list[str] = []
    for ref in finding.evidence:
        if ref.document:
            lines.append(f"- document {ref.document}"
                         + (f" section {ref.section}" if ref.section else ""))
            continue
        record = graph.by_key.get((ref.domain.upper(), ref.usubjid, ref.seq))
        if record is None:
            lines.append(f"- {ref.domain}:{ref.usubjid}:{ref.seq} (not found in the graph)")
            continue
        fields = {k: v for k, v in record.items()
                  if not k.startswith("_") and v not in (None, "")}
        # Resolve through the graph so a correction in force at this cut wins
        # over the raw CSV value, exactly as every detector sees it.
        resolved = {k: graph.record_value(record, k, cut) for k in fields}
        rendered = ", ".join(f"{k}={v}" for k, v in sorted(resolved.items()))
        lines.append(f"- {ref.domain}:{ref.usubjid}:{ref.seq} -> {rendered}")
    return "\n".join(lines) or "- (no record-level evidence cited)"
