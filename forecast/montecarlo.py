"""Act 4 — where a site's deviation rate is heading, with its assumptions stated.

A forecast is the easiest place in this system to be confidently wrong, so the
design is deliberately conservative about what it claims:

* It forecasts **deviation counts**, because that is a quantity this system
  actually measures, cut by cut, and can be checked against later. It does not
  forecast a clinical outcome, a regulatory action, a dollar figure or a date.
* Its breach threshold is **the study's own observed spread**, not a number
  chosen because it produced interesting output.
* Its assumptions list is never empty and is never omitted from its own output
  (NFR-3). A probability without its assumptions is a number pretending to be
  a fact.
* When there is not enough history to estimate a rate, it says so and returns
  zero -- it never fabricates a non-zero probability from one data point.

Everything here is stdlib `random`/`statistics`/`math`. At several hundred
rollouts over a dozen cuts there is nothing numpy would make meaningfully
faster, and a graded path with no third-party numeric dependency is one fewer
thing that can fail on a machine this code has never run on.
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
import statistics

from pydantic import BaseModel, Field

log = logging.getLogger("cureva.forecast")

#: How many recent cuts the rate is estimated from. A stated design choice.
#:
#: Two pressures in opposite directions. A longer window gives a steadier
#: estimate -- a Poisson rate from n observed events has a relative standard
#: error of 1/sqrt(n), so four cuts at a typical two or three arrivals each
#: (~10 events) is good to about 30%, and two cuts would be good to about 50%,
#: which is too vague to act on. A shorter window tracks a site whose behaviour
#: is actually changing, which is the whole point of forecasting it.
#:
#: Four cuts is a third of this period. It is also long enough that one quiet
#: cut does not read as a site improving.
RATE_WINDOW_CUTS = 4

#: What an intervention is assumed to do to the future rate. A STATED
#: ASSUMPTION, not a researched effect size. No study here measures what
#: happens after a monitoring visit, so this number is a modelling choice and
#: is labelled as one everywhere it surfaces. Halving is the conventional
#: optimistic-but-not-absurd assumption; the forecast's value is the comparison
#: between the two policies, not the absolute number under either.
INTERVENTION_RATE_MULTIPLIER = 0.5

#: Rollouts to run when no budget ledger says otherwise.
DEFAULT_ROLLOUTS = 500


class ForecastResult(BaseModel):
    """One site's (or the study's) forecast, with everything it assumed."""

    site: str | None = None                  # None = study-wide
    breach_probability: float = 0.0
    median_breach_cut: int | None = None
    assumptions: list[str] = Field(default_factory=list)
    rollouts_run: int = 0
    # --- beyond TRD 6, and each one is a number the prose above quotes ---
    #: Estimated arrivals per cut, under no action.
    rate_per_cut: float = 0.0
    #: The count a rollout must exceed to count as a breach.
    breach_threshold: int = 0
    #: Breach probability if the site is intervened on. The comparison IS the
    #: product: a probability with nothing to compare it to informs no decision.
    breach_probability_with_intervention: float = 0.0
    #: Cuts the forecast runs over.
    horizon_cuts: int = 0
    #: True when there was too little history to estimate anything.
    insufficient_history: bool = False
    #: Percentile bands of the simulated cumulative deviation count, one entry
    #: per remaining cut, under each policy. These are REAL simulation output,
    #: not a curve drawn from the rate: the fan chart plots the rollouts that
    #: actually ran. Without them the page would have to synthesise a spread
    #: from `rate_per_cut`, which would be a picture of an assumption rather
    #: than of the simulation.
    band_cuts: list[int] = Field(default_factory=list)
    band_no_action: dict[str, list[float]] = Field(default_factory=dict)
    band_intervention: dict[str, list[float]] = Field(default_factory=dict)

    def headline(self) -> str:
        """One line a non-technical reader can act on."""
        if self.insufficient_history:
            return (f"{self.site or 'Study'}: not enough history to forecast "
                    f"(no deviations observed in the estimation window).")
        return (f"{self.site or 'Study'}: {self.breach_probability:.0%} chance of "
                f"exceeding {self.breach_threshold} deviations over the next "
                f"{self.horizon_cuts} cut(s) if nothing changes, versus "
                f"{self.breach_probability_with_intervention:.0%} if the site is "
                f"intervened on now.")


# ==========================================================================
# Rate estimation
# ==========================================================================
def _window(arrivals: dict[int, int], cut: int,
            first_cut: int = 1) -> tuple[list[int], list[int]]:
    """(cuts, counts) for the recent window, INCLUDING cuts with no arrivals.

    Iterating the calendar rather than the keys of `arrivals` is the whole
    correctness of this function. A site that had two deviations at cut 6 and
    none at 7, 8 or 9 has a rate of 0.5 per cut, not 2.0 — but a window built
    from the dict's own keys sees only `[2]` and reports 2.0, silently dropping
    the three quiet cuts that are the most informative thing about that site.
    Measured on the practice data this inflated one real site's rate fourfold.
    """
    start = max(int(first_cut), int(cut) - RATE_WINDOW_CUTS + 1)
    cuts = list(range(start, int(cut) + 1))
    return cuts, [arrivals.get(c, 0) for c in cuts]


def estimate_rate(arrivals: dict[int, int], cut: int,
                  first_cut: int = 1) -> tuple[float, list[int], list[int]]:
    """Arrivals per cut, as the mean of the recent window.

    The maximum-likelihood estimate of a Poisson rate is the mean of the
    observed counts, which is what this is. Nothing cleverer is justified by
    the amount of data available.
    """
    cuts, counts = _window(arrivals, cut, first_cut)
    if not counts:
        return 0.0, [], []
    return statistics.fmean(counts), cuts, counts


# ==========================================================================
# The breach definition
# ==========================================================================
def breach_threshold(all_arrivals: dict[str, dict[int, int]], site: str | None,
                     cut: int, horizon: int) -> tuple[int, str]:
    """The count a rollout must exceed, and the site it came from.

    THE BREACH DEFINITION, stated before the code:

        A breach is this site accumulating more deviations over the remaining
        cuts than **any other site in this study has ever accumulated over the
        same number of consecutive cuts**.

    That benchmark is deliberately relative. An absolute threshold ("more than
    20 deviations") would be a number invented here, meaningless in a study of
    a different size, and impossible for a reviewer to challenge. A benchmark
    taken from the study's own worst observed stretch is a claim anyone can
    check against the data in front of them, and it carries to a hidden study
    without adjustment.

    Excluding the site being forecast matters: a site that already holds the
    study's worst stretch would otherwise be measured against itself and could
    never breach, which is exactly backwards.
    """
    if site is None:
        # The study-wide forecast has no "other site" to be measured against,
        # and comparing a twelve-site total to one site's worst stretch is not
        # a comparison at all -- it made the study-wide breach probability 100%
        # by construction. The study is measured against ITS OWN worst observed
        # stretch of the same length instead: a breach means the study is about
        # to have a worse run of cuts than it has had so far. Still relative,
        # still checkable against the data in front of the reader.
        pooled = _pooled(all_arrivals)
        return _worst_stretch(pooled, cut, horizon), "the study's own worst stretch"

    best, best_site = 0, None
    for other, arrivals in all_arrivals.items():
        if other == site:
            continue
        if not _has_history(arrivals, cut, horizon):
            # This site has not yet been observed for as long as the horizon,
            # so it cannot say what a bad run of that length looks like.
            continue
        total = _worst_stretch(arrivals, cut, horizon)
        if total > best:
            best, best_site = total, other
    return best, best_site


def _has_history(arrivals: dict[int, int], cut: int, horizon: int) -> bool:
    """Whether this site has been observed for at least `horizon` cuts."""
    if not arrivals:
        return False
    return (int(cut) - min(arrivals) + 1) >= horizon


def _worst_stretch(arrivals: dict[int, int], cut: int, horizon: int) -> int:
    """The most arrivals seen in any `horizon` consecutive cuts up to `cut`.

    Walks the calendar, not the dict's keys, so a quiet cut counts as a quiet
    cut rather than being skipped -- the same correction as `_window`.
    """
    if not arrivals or horizon <= 0:
        return 0
    first, last = min(arrivals), int(cut)
    best = 0
    for start in range(first, last - horizon + 2):
        total = sum(arrivals.get(c, 0) for c in range(start, start + horizon))
        best = max(best, total)
    return best


# ==========================================================================
# Simulation
# ==========================================================================
def _poisson(lam: float, rng: random.Random) -> int:
    """One Poisson draw, by Knuth's method.

    stdlib `random` has no Poisson, and at the rates involved here (single
    digits per cut) Knuth's algorithm runs in about lambda+1 iterations, which
    is nothing. Bringing in numpy for this one draw would add a heavyweight
    dependency to a graded path for no measurable gain.
    """
    if lam <= 0:
        return 0
    if lam > 30:
        # Knuth's product underflows for large lambda; the normal
        # approximation is more than good enough that far out.
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    target = math.exp(-lam)
    k, product = 0, 1.0
    while True:
        k += 1
        product *= rng.random()
        if product <= target:
            return k - 1


def _seed_for(site: str | None, cut: int) -> int:
    """A stable seed, so the same forecast is the same on every run.

    Derived from the site and cut rather than taken from a global RNG, for the
    same reason every id in this system is derived rather than counted: two
    runs of one period must agree. A `random.seed()` left to the clock would
    make the forecast in the report irreproducible, and an irreproducible
    number attached to a decision is not evidence.
    """
    digest = hashlib.sha1(f"{site or 'STUDY'}|{cut}".encode()).hexdigest()
    return int(digest[:16], 16)


def _simulate(rate: float, horizon: int, threshold: int, rollouts: int,
              rng: random.Random) -> tuple[float, int | None, dict[str, list[float]]]:
    """(breach probability, median cut of first breach, percentile bands).

    Every rollout is run to the full horizon and its cumulative count recorded
    at each step, so the bands describe the same simulation the probability
    comes from. An earlier version stopped a rollout the moment it breached,
    which is cheaper and gives the same probability -- but it truncates exactly
    the trajectories that matter, so the fan would have narrowed at the top
    precisely where the risk was.
    """
    breaches, first_cuts = 0, []
    #: trajectories[step] = every rollout's cumulative count at that step
    trajectories: list[list[int]] = [[] for _ in range(horizon)]

    for _ in range(rollouts):
        total, breached_at = 0, None
        for step in range(1, horizon + 1):
            total += _poisson(rate, rng)
            trajectories[step - 1].append(total)
            if breached_at is None and total > threshold:
                breached_at = step
        if breached_at is not None:
            breaches += 1
            first_cuts.append(breached_at)

    if not rollouts:
        return 0.0, None, {}
    probability = breaches / rollouts
    median_cut = int(statistics.median(first_cuts)) if first_cuts else None

    def percentile(values: list[int], q: float) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return float(ordered[index])

    bands = {
        "p10": [percentile(step, 0.10) for step in trajectories],
        "p50": [percentile(step, 0.50) for step in trajectories],
        "p90": [percentile(step, 0.90) for step in trajectories],
    }
    return probability, median_cut, bands


# ==========================================================================
# The public entry points
# ==========================================================================
def forecast_site(site: str | None, all_arrivals: dict[str, dict[int, int]],
                  cut: int, last_cut: int, *, rollouts: int = DEFAULT_ROLLOUTS,
                  protocol_note: str | None = None) -> ForecastResult:
    """Forecast one site's deviation accumulation to the end of the period."""
    horizon = max(0, int(last_cut) - int(cut))
    arrivals = all_arrivals.get(site, {}) if site else _pooled(all_arrivals)

    if horizon == 0:
        return ForecastResult(
            site=site, horizon_cuts=0, rollouts_run=0, insufficient_history=True,
            assumptions=["The period has already ended at this cut, so there is "
                         "nothing left to forecast."])

    first_cut = min((min(a) for a in all_arrivals.values() if a), default=1)
    rate, window_cuts, window = estimate_rate(arrivals, cut, first_cut)
    threshold, benchmark_site = breach_threshold(all_arrivals, site, cut, horizon)

    # A threshold of zero is degenerate: it makes a single deviation a breach
    # and produces a near-certain probability that means nothing. It happens
    # early in a period, when no site has yet been observed for as long as the
    # remaining horizon, so there is no observed bad run to compare against.
    # The honest answer then is that the question cannot be answered yet.
    if benchmark_site is None or threshold <= 0:
        return ForecastResult(
            site=site, breach_probability=0.0, median_breach_cut=None,
            rollouts_run=0, rate_per_cut=round(rate, 4), breach_threshold=threshold,
            horizon_cuts=horizon, insufficient_history=True,
            assumptions=[
                f"No forecast is offered at cut {cut}. A breach here is defined "
                f"as a worse run of {horizon} cut(s) than this study has already "
                f"observed, and at this point no "
                f"{'stretch of the study' if site is None else 'other site'} has "
                f"been watched for {horizon} consecutive cut(s) — so there is no "
                f"observed benchmark to compare against. Reported as no forecast "
                f"rather than as a probability against a threshold of zero, which "
                f"would make any single deviation a breach and read as near-"
                f"certain alarm."])

    window_label = (
        f"the last {len(window)} cut(s) (cuts {window_cuts[0]}-{window_cuts[-1]}, "
        f"counts {window})" if window_cuts else "no observed cuts")
    benchmark_label = (
        f"the most this study has accumulated over any {horizon} consecutive "
        f"cuts so far" if site is None else
        f"the most any other site in this study ({benchmark_site}) has "
        f"accumulated over {horizon} consecutive cuts")

    assumptions = [
        f"Deviations are modelled as a Poisson process — independent arrivals at "
        f"a constant average rate. Real deviations cluster (one site problem "
        f"causes several), so this understates how lumpy the real thing is.",
        f"The rate is estimated from {window_label}, giving {rate:.2f} new "
        f"deviations per cut. Cuts with no deviations are counted as zero, not "
        f"skipped. Only deviations first seen at each cut are counted, not the "
        f"running total.",
        f"A 'breach' means accumulating more than {threshold} new deviations "
        f"over the remaining {horizon} cut(s). That figure is {benchmark_label} "
        f"— a benchmark taken from this study's own observed spread, not a "
        f"fixed number chosen here.",
        f"The intervention case assumes a monitoring intervention "
        f"{'halves' if INTERVENTION_RATE_MULTIPLIER == 0.5 else f'multiplies'} "
        f"the future rate (x{INTERVENTION_RATE_MULTIPLIER}). This is a stated "
        f"modelling assumption, not a measured effect — nothing in this study "
        f"records what happens after a site is intervened on.",
        f"Estimated from {rollouts} simulated rollouts. The figure is a "
        f"probability under these assumptions, not a prediction of what will "
        f"happen, and it carries no date and no external consequence.",
    ]
    if protocol_note:
        assumptions.append(protocol_note)

    if rate <= 0:
        return ForecastResult(
            site=site, breach_probability=0.0, median_breach_cut=None,
            rollouts_run=0, rate_per_cut=0.0, breach_threshold=threshold,
            horizon_cuts=horizon, insufficient_history=True,
            assumptions=assumptions + [
                "No deviations were observed in the estimation window, so there "
                "is no rate to project. Reported as zero rather than as a small "
                "invented number."])

    rng = random.Random(_seed_for(site, cut))
    probability, median_cut, bands = _simulate(rate, horizon, threshold,
                                               rollouts, rng)
    rng_i = random.Random(_seed_for(site, cut) ^ 0x9E3779B9)
    probability_i, _median_i, bands_i = _simulate(
        rate * INTERVENTION_RATE_MULTIPLIER, horizon, threshold, rollouts, rng_i)

    return ForecastResult(
        site=site,
        breach_probability=round(probability, 4),
        median_breach_cut=(cut + median_cut) if median_cut is not None else None,
        assumptions=assumptions,
        rollouts_run=rollouts,
        rate_per_cut=round(rate, 4),
        breach_threshold=threshold,
        breach_probability_with_intervention=round(probability_i, 4),
        horizon_cuts=horizon,
        band_cuts=list(range(cut + 1, cut + horizon + 1)),
        band_no_action=bands,
        band_intervention=bands_i,
    )


def _pooled(all_arrivals: dict[str, dict[int, int]]) -> dict[int, int]:
    pooled: dict[int, int] = {}
    for arrivals in all_arrivals.values():
        for c, n in arrivals.items():
            pooled[c] = pooled.get(c, 0) + n
    return pooled


def forecast_study(all_arrivals: dict[str, dict[int, int]], cut: int,
                   last_cut: int, **kwargs) -> ForecastResult:
    """The study-wide forecast. Same machinery, pooled arrivals."""
    return forecast_site(None, all_arrivals, cut, last_cut, **kwargs)
