"""The two budget ledgers — what degrades first, and what never degrades.

PRD FR-14/FR-15 and TRD 6. Two ledgers, not one, because tokens and wall-clock
are genuinely different resources with genuinely different ceilings: Groq's
daily token limit is a property of the account and resets on its own schedule,
while the harness's time budget is a property of one run. Conflating them into
a single "budget" number degrades the wrong thing under the wrong pressure --
a run that is slow but has spent no tokens would start dropping LLM work that
costs it nothing, and a run that is fast but token-poor would keep making calls
it cannot afford.

**What never degrades, at any budget level, under any pressure:** DETECT,
COMPLIANCE, the HUMAN GATE, supersession tracking, and writing the trace. Every
one of those is deterministic, costs no tokens, and is the part of the system a
regulator would actually care about. The degradation order below only ever
reaches optional narrative and simulation work:

    1. Act 5's Groq polish        -> falls back to the template (same facts)
    2. Act 3's Tribunal           -> already off by default; rule verdict stands
    3. Monte Carlo rollout count  -> halved, never below a stated floor
    -----------------------------------------------------------------------
    (nothing below this line ever degrades)
    4. DETECT / COMPLIANCE / HUMAN GATE / trace-writing

Both ledgers are checked *before* a call is attempted, never after. Reading
Groq's own 429 as the signal would mean the budget is only discovered by
exceeding it, and a rate-limit error is not a plan.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from pydantic import BaseModel, Field

log = logging.getLogger("cureva.stage3.budget")

# ==========================================================================
# Token ledger — sized against Groq's real daily limit (T3.0, re-verified)
# ==========================================================================
#: Groq's free-tier tokens-per-day for `openai/gpt-oss-20b`, re-verified
#: against Groq's own documentation during T3.0 on 2026-09-19 and unchanged
#: from Stage 2's measurement. The live response headers confirm the companion
#: limits directly (`x-ratelimit-limit-tokens: 8000` per minute,
#: `x-ratelimit-limit-requests: 1000` per day); TPD is not exposed in any
#: header, so the documented figure is the only source and is recorded as such
#: rather than claimed as measured.
GROQ_TOKENS_PER_DAY = 200_000

#: What one period walk may spend. A stated design choice, with the arithmetic
#: rather than a round number chosen because it looked prudent.
#:
#: The daily limit is per ACCOUNT, and every Groq-touching part of this system
#: draws from the same pool on the same day: Stage 1's patient avatar, Act 3's
#: Tribunal if it is ever switched on, and Act 5's polish. On demo day that
#: pool has to cover development runs, at least one full rehearsal, and the
#: live demo itself.
#:
#:     rehearsal walk        20,000
#:     live demo walk        20,000
#:     avatar during demo   ~20,000   (~10 turns at ~2k tokens)
#:                          -------
#:                           60,000   = 30% of the day
#:
#: leaving 140,000 (70%) for development and for anything that has to be re-run
#: after a failure. At 20,000 a period walk could be run ten times in one day
#: and still not exhaust the account, which is the margin that matters: the
#: failure this ledger exists to prevent is discovering the limit live.
PERIOD_TOKEN_CEILING = 20_000

#: Estimate for one Act 5 polish call, in tokens.
#:
#: MEASURED, not guessed: a real polish call against a real IRB memo on
#: 2026-09-19 reported 851 total tokens. The estimate is kept at 1,200 rather
#: than lowered to the measurement, because over-estimating is the safe
#: direction for a ledger -- it can only cause polish to be skipped slightly
#: early, never to be attempted with nothing left to pay for it -- and because
#: an artifact citing more records than that memo did will cost more. At 1,200
#: the period ceiling affords roughly 16 polish calls, which is more than the
#: number of IRB memos a period produces.
POLISH_ESTIMATED_TOKENS = 1_200

#: What one real call actually cost, for the record.
POLISH_MEASURED_TOKENS = 851


class TokenLedger(BaseModel):
    """Cumulative Groq spend for one period, against a stated ceiling."""

    ceiling: int = PERIOD_TOKEN_CEILING
    spent: int = 0
    #: Every skip, with what was asked for and what was left. The ledger is
    #: evidence, not just a counter -- NFR-3 means a run that degraded has to
    #: be able to say so afterwards, precisely.
    skipped: list[str] = Field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.ceiling - self.spent)

    def can_afford(self, estimated: int) -> bool:
        """Whether a call of this estimated size may be attempted at all.

        Checked BEFORE the call. A component that made the call and then looked
        at the error would be learning its budget by exceeding it.
        """
        return estimated <= self.remaining

    def debit(self, actual: int) -> int:
        """Record real spend. Returns the new total.

        Takes the ACTUAL token count from the provider's own usage block, never
        the estimate -- an estimate that drifted from reality would make the
        ledger a guess about a quantity that is measured for us on every call.
        """
        self.spent += max(0, int(actual))
        return self.spent

    def skip(self, what: str, estimated: int) -> None:
        """Record that something was skipped because it could not be afforded."""
        message = (f"{what}: needed ~{estimated} tokens, {self.remaining} left of "
                   f"{self.ceiling}")
        self.skipped.append(message)
        log.info("token budget: skipped %s", message)

    def summary(self) -> dict:
        return {
            "ceiling": self.ceiling,
            "spent": self.spent,
            "remaining": self.remaining,
            "skipped": len(self.skipped),
            "skips": list(self.skipped),
            "daily_limit": GROQ_TOKENS_PER_DAY,
            "share_of_daily_limit": round(self.ceiling / GROQ_TOKENS_PER_DAY, 4),
        }


# ==========================================================================
# Time ledger — governs Monte Carlo, never a deterministic check
# ==========================================================================
#: Where the rollout count starts. PRD FR-17 asks for "several hundred".
DEFAULT_ROLLOUT_CEILING = 500

#: The floor the rollout count never drops below. A stated design choice.
#:
#: A breach probability estimated from n rollouts is a binomial proportion, so
#: its standard error is at most sqrt(0.25 / n) -- worst case, at p = 0.5. At
#: n = 50 that is 0.071, so the estimate is good to about +/- 7 percentage
#: points, which still separates "unlikely" from "roughly even" from "likely".
#: That is the resolution a forecast attached to an escalation actually needs.
#: Below 50 the error passes 10 points and the number stops supporting any
#: statement worth making, so degrading further would not be a cheaper answer,
#: it would be a meaningless one -- and `ForecastResult.rollouts_run` reports
#: the real count so a reader can see the precision they are being given.
ROLLOUT_FLOOR = 50

#: Fractions of the deadline at which the rollout ceiling halves. Stated rule:
#: each threshold crossed halves the ceiling, and it never falls below the
#: floor. 500 -> 250 -> 125 -> 62 -> (floor) 50.
#:
#: The last threshold is 1.00 deliberately. With only three thresholds the
#: sequence bottoms out at 62 and the floor is never actually reached -- a
#: declared floor that no amount of pressure can reach is not a floor, it is a
#: comment. The fourth halving is what makes ROLLOUT_FLOOR the real, reachable
#: minimum once the deadline is genuinely gone.
DEGRADE_AT: tuple[float, ...] = (0.50, 0.75, 0.90, 1.00)

#: Default wall-clock budget for one period walk, in seconds. The measured
#: deterministic walk is ~3s on the practice study (T3.3), so this is not a
#: constraint in normal operation -- it is the ceiling that stops an unlucky
#: run from spending its whole budget in the simulator.
DEFAULT_DEADLINE_S = 90.0


class TimeLedger(BaseModel):
    """Wall-clock budget, degrading rollout count and nothing else."""

    rollout_ceiling: int = DEFAULT_ROLLOUT_CEILING
    floor: int = ROLLOUT_FLOOR
    hard_deadline_s: float = DEFAULT_DEADLINE_S
    started_at: float = Field(default_factory=time.monotonic)
    rollouts_run: int = 0
    #: Each degradation step, for the report.
    degradations: list[str] = Field(default_factory=list)

    #: Injectable clock. Tests drive elapsed time directly rather than sleeping
    #: through a ninety-second deadline to observe a branch.
    _clock: Callable[[], float] | None = None
    #: Rollout ceilings already reported, so each real step is logged once.
    _recorded_steps: set[int] = set()

    model_config = {"arbitrary_types_allowed": True}

    def model_post_init(self, __context) -> None:
        # Per-instance, never shared: a class-level mutable default would make
        # two ledgers in one process silence each other's degradation notes.
        self._recorded_steps = set()

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def elapsed_s(self) -> float:
        return max(0.0, self._now() - self.started_at)

    def fraction_used(self) -> float:
        if self.hard_deadline_s <= 0:
            return 1.0
        return self.elapsed_s() / self.hard_deadline_s

    def rollouts_for_next_call(self) -> int:
        """How many rollouts the next Monte Carlo run may use.

        Applies the stated degradation rule against the clock as it stands now,
        and never returns less than the floor. This is the only lever the time
        ledger pulls: no deterministic check consults it, and none ever will.
        """
        used = self.fraction_used()
        crossed = sum(1 for threshold in DEGRADE_AT if used >= threshold)
        allowed = self.rollout_ceiling
        for _ in range(crossed):
            allowed //= 2
        allowed = max(self.floor, allowed)

        if crossed and allowed != self.rollout_ceiling:
            # Recorded once per distinct STEP, not once per call. Keying the
            # dedup on the note text does not work -- the text carries the
            # elapsed percentage, which differs on every call, so four real
            # degradations were being logged as eight lines. The step is
            # identified by the ceiling it lands on.
            if allowed not in self._recorded_steps:
                self._recorded_steps.add(allowed)
                threshold = DEGRADE_AT[crossed - 1]
                note = (f"past {threshold:.0%} of the {self.hard_deadline_s:.0f}s "
                        f"budget; rollouts {self.rollout_ceiling} -> {allowed}"
                        + (" (floor — degrades no further)"
                           if allowed == self.floor else ""))
                self.degradations.append(note)
                log.info("time budget: %s", note)
        return allowed

    def note_rollouts(self, count: int) -> None:
        self.rollouts_run += max(0, int(count))

    def expired(self) -> bool:
        """True once the deadline is genuinely gone.

        Even here, nothing deterministic is skipped. The only thing this
        switches off is the optional simulation.
        """
        return self.fraction_used() >= 1.0

    def summary(self) -> dict:
        return {
            "rollout_ceiling": self.rollout_ceiling,
            "rollout_floor": self.floor,
            "rollouts_available_now": self.rollouts_for_next_call(),
            "rollouts_run": self.rollouts_run,
            "hard_deadline_s": self.hard_deadline_s,
            "elapsed_s": round(self.elapsed_s(), 3),
            "degradations": list(self.degradations),
        }


#: The stated order in which work is given up under budget pressure, and the
#: line below which nothing ever is. Surfaced in the surveillance report so a
#: reader can see what a degraded run gave up, rather than having to infer it.
DEGRADATION_ORDER: tuple[str, ...] = (
    "Act 5 LLM polish (falls back to the template — same facts, plainer prose)",
    "Act 3 Tribunal (off by default; the rule-based verdict is unchanged)",
    "Monte Carlo rollout count (halved, never below the stated floor)",
)

NEVER_DEGRADES: tuple[str, ...] = (
    "DETECT — every detector, every cut",
    "COMPLIANCE — protocol deviations",
    "HUMAN GATE — escalations and their decisions",
    "Supersession tracking",
    "Trace writing",
)
