"""Cross-cut memory — what makes the second walk of a period agree with the first.

The hard requirement this file exists to satisfy (PRD FR-3, TRD 8): every piece
of state Watch accumulates as it walks must be **re-derivable identically from a
re-run of the same period**. Stage 2 found that class of bug twice -- a counter
that summed across cycles, and a watch keyed on cycle-count instead of cut --
and the Stage 3 ground-truth table names this file as the first place to check
for it again. So nothing here appends, increments or counts. Every structure is
keyed on the thing it describes, and writing the same cut twice writes the same
value twice.

## Where this deviates from `cureva-stage3-trd.md` 6, and why

Three deviations, each forced by a real conflict inside the TRD itself rather
than chosen for convenience. Flagged here rather than applied silently, the
same discipline `stage2/models.py` used for its own three.

* **`SiteTrendHistory.series` is `dict[str, dict[int, float]]`, not
  `dict[str, list[float]]`.** TRD 6 writes it as a list ("values per cut seen so
  far"); TRD 8 requires that "re-processing the same cut twice leaves it
  unchanged". A list that grows by one per cut cannot satisfy both -- walking
  cut 3 a second time appends a second cut-3 value, and every downstream
  consecutive-cut ratio (T3.6) then compares a cut against itself. Keying the
  value by its own cut number makes the write idempotent by construction: the
  second walk assigns the same value to the same key. This is the identical
  correction Stage 2 applied to `sae_unescalated_watch` (keyed on cut, not
  cycle), for the identical reason. `dict[int, float]` round-trips through JSON
  under pydantic v2 (verified: keys come back as `int`).

* **Three fields exist that TRD 6 does not list** -- `finding_first_cut`,
  `document_digests` and `cuts_walked`. Each is state a later task genuinely
  cannot reconstruct after the fact:
  - `finding_first_cut` is `SupersededFinding.first_raised_cut`'s only source.
    Once a finding stops being detected, the cut it was *first* seen at is not
    recoverable from the current cut's sweep -- the information exists only
    while the finding is still being observed, so it has to be written down as
    the walk passes.
  - `document_digests` is what makes T3.7 a cut-over-cut detector at all. A
    document's content at an earlier cut is not otherwise retrievable; the file
    on disk only ever shows its current state.
  - `cuts_walked` records which cuts this memory has actually seen, so a
    resumed walk (TNFR-4) knows what it already did.

* **`tokens_spent_this_period` and `rollouts_run_this_period` are reset by
  `begin_period()`**, not carried forward indefinitely. They are named "this
  period" and the budget ledgers they feed are per-period budgets. Left
  cumulative, a second walk of the same period would report double the first
  walk's spend -- which is exactly the summed-counter bug in a new costume.
  Reset at period start, a re-walk reports the same totals; within a period they
  persist across a snapshot, so an interrupted walk resumes with its spend
  intact.

A snapshot that cannot be read is not a fatal condition (NFR-2): memory starts
empty and says so, mirroring `CrewMemory.load()` exactly. Trusting a
half-written file would be worse than forgetting.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger("cureva.stage3.memory")

DEFAULT_SNAPSHOT_PATH = Path("state/watch_memory_snapshot.json")

#: Namespace prefixes for `SiteTrendHistory.series`. A hidden study is free to
#: have a laboratory test literally called "deviations", so the two kinds of
#: series are kept in separate namespaces rather than sharing one flat key.
LAB_SERIES = "LB"      # LB:<LBTESTCD> -> {cut: representative value}
KRI_SERIES = "KRI"     # KRI:<metric>  -> {cut: metric value}


def lab_series_key(testcd: str, unit: str | None = None) -> str:
    """Series key for one laboratory test, optionally qualified by its unit.

    The unit belongs in the key. `LAB_UNIT_CORRUPTION` (T3.6) is the claim
    "these values changed scale while still claiming the same unit", and that
    claim is only meaningful within one unit label -- a site that genuinely
    switches from U/L to ukat/L has a `LAB_UNIT_MISMATCH`, which Stage 1
    already detects, not a corruption. Keeping the unit in the key stops the
    two being compared against each other and read as a scale shift.
    """
    testcd = (testcd or "").strip().upper()
    if unit is None:
        return f"{LAB_SERIES}:{testcd}"
    return f"{LAB_SERIES}:{testcd}@{(unit or '').strip()}"


def split_lab_series_key(key: str) -> tuple[str, str]:
    """(testcd, unit) back out of a key produced by `lab_series_key`."""
    body = key.split(":", 1)[1] if ":" in key else key
    testcd, _, unit = body.partition("@")
    return testcd, unit


def dispersion_series_key(testcd: str, unit: str | None = None) -> str:
    """Series key for a test's *within-cut* spread, parallel to its median.

    Kept as its own series rather than folded into the value series: they are
    different quantities measured on the same records, and T3.8 needs to read
    them independently.
    """
    return "DISP:" + lab_series_key(testcd, unit).split(":", 1)[1]


def kri_series_key(metric: str) -> str:
    return f"{KRI_SERIES}:{(metric or '').strip().lower()}"


#: KRI series names used by the trend detectors.
LAG_METRIC = "lag_days"          # this site's median reporting lag at a cut


def digest(text: str) -> str:
    """Content hash of a document, for cut-over-cut change detection (T3.7)."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


# ==========================================================================
# Models — TRD 6, with the three deviations this module's docstring states
# ==========================================================================
class SupersededFinding(BaseModel):
    """A finding that stopped being detected, and the honest reason why.

    `reason` is load-bearing and is never a guess. Audit 10 found that a
    finding can disappear for a reason that is not a correction -- Stage 2
    permanently retires a `SAE_UNESCALATED` once it has been escalated -- so
    absence alone never justifies claiming a correction superseded anything.
    """

    finding_id: str
    escalation_id: str | None = None
    first_raised_cut: int
    superseded_at_cut: int
    reason: str
    #: What actually explains the absence. Kept separate from the prose so the
    #: report can count the two kinds without parsing `reason`.
    cause: str = "no_longer_detected"


class SiteTrendHistory(BaseModel):
    """One site's rolling per-cut series, keyed by cut rather than appended."""

    site: str
    series: dict[str, dict[int, float]] = Field(default_factory=dict)

    def observe(self, key: str, cut: int, value: float) -> None:
        """Record one value. Assignment, never append -- see module docstring."""
        self.series.setdefault(key, {})[int(cut)] = float(value)

    def at(self, key: str, cut: int) -> float | None:
        return self.series.get(key, {}).get(int(cut))

    def cuts_for(self, key: str) -> list[int]:
        return sorted(self.series.get(key, {}))

    def values_upto(self, key: str, cut: int) -> list[tuple[int, float]]:
        """(cut, value) pairs at or before `cut`, in cut order.

        Bounded by `cut` so a detector running at cut N can never read a value
        from cut N+1 that a previous, longer walk happened to leave in memory.
        """
        series = self.series.get(key, {})
        return [(c, series[c]) for c in sorted(series) if c <= int(cut)]


class WatchMemorySnapshot(BaseModel):
    """The whole of cross-cut memory, as written to disk after every cut."""

    trend_history: dict[str, SiteTrendHistory] = Field(default_factory=dict)
    superseded: list[SupersededFinding] = Field(default_factory=list)
    pending_queue: dict[str, int] = Field(default_factory=dict)
    asked_at: dict[str, int] = Field(default_factory=dict)
    tokens_spent_this_period: int = 0
    rollouts_run_this_period: int = 0
    # --- beyond TRD 6; see module docstring for why each is unavoidable ---
    finding_first_cut: dict[str, int] = Field(default_factory=dict)
    document_digests: dict[str, dict[int, str]] = Field(default_factory=dict)
    cuts_walked: list[int] = Field(default_factory=list)


# ==========================================================================
# The live object
# ==========================================================================
class WatchMemory:
    """Everything `StudyWatch` remembers between cuts."""

    def __init__(self, snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH):
        self.snapshot_path = Path(snapshot_path)
        self.trend_history: dict[str, SiteTrendHistory] = {}
        self.superseded: list[SupersededFinding] = []
        self.pending_queue: dict[str, int] = {}
        #: escalation_id -> the cut the monitor was actually asked at. Kept so
        #: the report can say how long each answer really took, rather than
        #: only that it eventually arrived.
        self.asked_at: dict[str, int] = {}
        self.tokens_spent_this_period: int = 0
        self.rollouts_run_this_period: int = 0
        self.finding_first_cut: dict[str, int] = {}
        self.document_digests: dict[str, dict[int, str]] = {}
        self.cuts_walked: list[int] = []

    # ------------------------------------------------------------ lifecycle
    def begin_period(self) -> None:
        """Reset the two period-scoped spend counters. Nothing else is cleared.

        Trend history, supersessions and the pending queue all deliberately
        survive: they are the cross-cut knowledge the next walk is supposed to
        start from. Only the two "this period" totals reset, so a second walk
        reports the same spend as the first rather than twice it.
        """
        self.tokens_spent_this_period = 0
        self.rollouts_run_this_period = 0

    # ------------------------------------------------------- trend history
    def site_history(self, site: str) -> SiteTrendHistory:
        """The site's history, created on first sight.

        Never keyed on a site name this code knows in advance -- a site that
        appears for the first time at cut 6 gets an entry at cut 6, which is
        what makes onboarding (FR-13) free rather than a code change.
        """
        entry = self.trend_history.get(site)
        if entry is None:
            entry = SiteTrendHistory(site=site)
            self.trend_history[site] = entry
        return entry

    def observe(self, site: str, key: str, cut: int, value: float) -> None:
        self.site_history(site).observe(key, cut, value)

    # ------------------------------------------------------------- findings
    def note_finding(self, finding_id: str, cut: int) -> int:
        """Record the earliest cut a finding was seen at. Returns that cut.

        `min`, not "first write wins", so walking cuts out of order still
        yields the genuinely earliest cut, and walking the same cut twice
        changes nothing.
        """
        cut = int(cut)
        current = self.finding_first_cut.get(finding_id)
        earliest = cut if current is None else min(current, cut)
        self.finding_first_cut[finding_id] = earliest
        return earliest

    def record_superseded(self, entry: SupersededFinding) -> None:
        """Record a supersession, at most once per finding.

        A list that appended on every cut would grow a duplicate entry for the
        same finding at every subsequent cut it stayed absent.
        """
        for existing in self.superseded:
            if existing.finding_id == entry.finding_id:
                return
        self.superseded.append(entry)

    # ------------------------------------------------------------ documents
    def observe_document(self, name: str, cut: int, text: str) -> str:
        """Record a document's content hash at a cut. Returns the digest."""
        d = digest(text)
        self.document_digests.setdefault(name, {})[int(cut)] = d
        return d

    def document_digest_before(self, name: str, cut: int) -> tuple[int, str] | None:
        """(cut, digest) of the newest record strictly before `cut`, if any."""
        seen = self.document_digests.get(name, {})
        earlier = [c for c in seen if c < int(cut)]
        if not earlier:
            return None
        newest = max(earlier)
        return newest, seen[newest]

    # ----------------------------------------------------------------- cuts
    def note_cut(self, cut: int) -> None:
        """Record that this cut has been walked. Idempotent by set semantics."""
        cut = int(cut)
        if cut not in self.cuts_walked:
            self.cuts_walked.append(cut)
            self.cuts_walked.sort()

    # ------------------------------------------------------- serialisation
    def to_snapshot(self) -> WatchMemorySnapshot:
        return WatchMemorySnapshot(
            trend_history=dict(self.trend_history),
            superseded=list(self.superseded),
            pending_queue=dict(self.pending_queue),
            asked_at=dict(self.asked_at),
            tokens_spent_this_period=self.tokens_spent_this_period,
            rollouts_run_this_period=self.rollouts_run_this_period,
            finding_first_cut=dict(self.finding_first_cut),
            document_digests={k: dict(v) for k, v in self.document_digests.items()},
            cuts_walked=list(self.cuts_walked),
        )

    def snapshot(self, path: str | Path | None = None) -> Path:
        """Write the whole of memory as JSON. Called after every cut."""
        target = Path(path) if path is not None else self.snapshot_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_snapshot().model_dump(mode="json")
        # Write-then-rename, exactly as `CrewMemory.snapshot` does: a crash
        # mid-write leaves the previous good snapshot rather than a truncated
        # file that load() would then have to reject.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(target)
        return target

    def load(self, path: str | Path | None = None) -> bool:
        """Restore memory from a snapshot.

        Returns True when state was restored. A missing or unreadable file
        leaves memory empty, logs a warning and returns False -- never raises
        (NFR-2), matching `CrewMemory.load()`'s precedent exactly.
        """
        target = Path(path) if path is not None else self.snapshot_path
        if not target.exists():
            log.warning("no watch memory snapshot at %s - starting with empty memory",
                        target)
            return False
        try:
            snap = WatchMemorySnapshot.model_validate_json(target.read_text())
        except Exception as exc:                                  # noqa: BLE001
            log.warning("watch memory snapshot at %s is unreadable (%s: %s) - "
                        "starting with empty memory", target, type(exc).__name__, exc)
            return False
        self.trend_history = dict(snap.trend_history)
        self.superseded = list(snap.superseded)
        self.pending_queue = dict(snap.pending_queue)
        self.asked_at = dict(snap.asked_at)
        self.tokens_spent_this_period = snap.tokens_spent_this_period
        self.rollouts_run_this_period = snap.rollouts_run_this_period
        self.finding_first_cut = dict(snap.finding_first_cut)
        self.document_digests = {k: dict(v) for k, v in snap.document_digests.items()}
        self.cuts_walked = list(snap.cuts_walked)
        return True

    def sizes(self) -> dict[str, int]:
        """Counts used by the idempotency checks and the manual spot-check."""
        return {
            "trend_history_sites": len(self.trend_history),
            "trend_series": sum(len(h.series) for h in self.trend_history.values()),
            "trend_points": sum(len(s) for h in self.trend_history.values()
                                for s in h.series.values()),
            "superseded": len(self.superseded),
            "pending_queue": len(self.pending_queue),
            "asked_at": len(self.asked_at),
            "finding_first_cut": len(self.finding_first_cut),
            "documents_tracked": len(self.document_digests),
            "cuts_walked": len(self.cuts_walked),
            "tokens_spent_this_period": self.tokens_spent_this_period,
            "rollouts_run_this_period": self.rollouts_run_this_period,
        }
