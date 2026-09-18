"""Act 3 — the Tribunal.

Called from inside the graded cycle, which is a deliberate departure from the
way Act 1/2 were isolated in the earlier layer. Isolation here means "can never
block or corrupt the result", not "never runs":

* the rule-based verdict is computed and recorded *before* this is attempted;
* the whole attempt is bounded by one timeout;
* `deliberate()` never raises -- every failure comes back as a transcript with
  `ran=False` and a real reason.

The public surface is one function, so the crew has exactly one call site to
wrap.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tribunal.models import Arbitration, TribunalTranscript
from tribunal.round1 import run_round1
from tribunal.round2 import run_round2
from tribunal.round3 import arbitrate

log = logging.getLogger("cureva.tribunal")

#: Rounds 1+2 combined, per TRD 7. Round 3 is local and instant.
TRIBUNAL_TIMEOUT_SECONDS = 12.0

__all__ = ["deliberate", "TribunalTranscript", "TRIBUNAL_TIMEOUT_SECONDS"]


def _skipped(finding_id: str, reason: str, started: float,
             tokens: int = 0) -> TribunalTranscript:
    return TribunalTranscript(
        finding_id=finding_id, ran=False, skip_reason=reason, tokens_used=tokens,
        duration_ms=int(round((time.perf_counter() - started) * 1000)))


async def _deliberate_async(atlas: Any, finding: Any, finding_id: str, cut: int | None,
                            client: Any) -> tuple[list, list, int, list[str]]:
    round1, t1, reasons = await run_round1(client, finding, finding_id, atlas.graph, cut)
    if not round1:
        return [], [], t1, reasons
    round2, t2 = await run_round2(client, finding, finding_id, round1, atlas.graph, cut)
    return round1, round2, t1 + t2, reasons


def deliberate(atlas: Any, finding: Any, finding_id: str, cut: int | None,
               *, client: Any = None,
               timeout: float = TRIBUNAL_TIMEOUT_SECONDS) -> TribunalTranscript:
    """Run all three rounds for one finding. Never raises.

    Rounds 1 and 2 are bounded by `timeout` together. Round 3 runs afterwards
    and is deterministic, so it is deliberately *outside* the timeout: having
    paid for two rounds of model calls, throwing away the free fact-check over
    a stopwatch would be the one saving that costs something.
    """
    started = time.perf_counter()
    try:
        if client is None:
            from tribunal.client import make_client
            client = make_client()
    except Exception as exc:                                      # noqa: BLE001
        return _skipped(finding_id, f"{type(exc).__name__}: {exc}", started)

    tokens = 0
    reasons: list[str] = []
    try:
        round1, round2, tokens, reasons = asyncio.run(
            asyncio.wait_for(
                _deliberate_async(atlas, finding, finding_id, cut, client),
                timeout=timeout))
    except TimeoutError:
        return _skipped(finding_id, f"timed out after {timeout:.0f}s", started)
    except Exception as exc:                                      # noqa: BLE001
        return _skipped(finding_id, f"{type(exc).__name__}: {exc}", started, tokens)

    if not round1:
        # Say what actually went wrong. "No verdict" alone is the kind of
        # message that makes a live failure look like an empty result, which
        # is precisely the confusion a visible degradation is meant to avoid.
        detail = "; ".join(dict.fromkeys(reasons)) or "no persona produced a valid verdict"
        return _skipped(finding_id, detail, started, tokens)

    try:
        round3: Arbitration | None = arbitrate(
            atlas, finding, finding_id, round1, round2, cut)
    except Exception as exc:                                      # noqa: BLE001
        log.warning("round 3 failed for %s: %s", finding_id, exc)
        round3 = None

    return TribunalTranscript(
        finding_id=finding_id, round1=round1, round2=round2, round3=round3,
        ran=True, tokens_used=tokens,
        duration_ms=int(round((time.perf_counter() - started) * 1000)))
