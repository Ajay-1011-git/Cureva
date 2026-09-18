"""Cross-cycle memory — what makes a second review of the same cut a no-op.

The hard requirement this file exists to satisfy (PRD G2/FR-16, NFR-5): running
`run_cycle()` twice with the same `(cut, protocol_version)` raises zero new
queries and zero new escalations. Everything below is shaped by that, including
two choices that look conservative until you try the alternative:

* **Flag counters store a maximum, not a running sum.** `subject_flags` feeds
  MEDICAL REVIEW's compounding rule ("this subject already has >=2 flagged
  findings"). If the counter accumulated on every cycle, a second pass over the
  same cut would push borderline subjects over the threshold, flip monitor-only
  findings to escalation-worthy, and raise new escalations -- breaking the one
  property the whole stage is graded on. Storing the highest count ever seen in
  a single cycle keeps the signal ("this subject is repeatedly messy") while
  making a repeat cycle arithmetically identical to the first.
* **The SAE watch is keyed on cut, not cycle.** Same reasoning, stated where it
  is used, in `crew.py`.

A memory snapshot that cannot be read is not a fatal condition (FR-15): memory
starts empty and says so. Trusting a half-written file would be worse than
forgetting -- forgetting re-raises queries that were already raised, which is
visible and recoverable; trusting corrupt state silently suppresses real ones.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from schemas import QueryOut

from stage2.models import CrewMemorySnapshot, EscalationRecord

log = logging.getLogger("cureva.stage2.memory")

DEFAULT_SNAPSHOT_PATH = Path("state/memory_snapshot.json")


def query_key(domain: str, usubjid: str | None, seq: int | None) -> str:
    """The dedup key for one query.

    Exactly the three values `study.query_site()` itself keys on. TRD 6 adds a
    fourth component, `field`, which no organiser type carries -- see
    `docs/stage2-contract-audit.md` 3.
    """
    return f"{domain}:{usubjid or ''}:{'' if seq is None else seq}"


class CrewMemory:
    """Everything `ReviewCrew` remembers between cycles."""

    def __init__(self, snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH):
        self.snapshot_path = Path(snapshot_path)
        self.cycle_number: int = 0
        self.queries_raised: set[str] = set()
        self.query_records: dict[str, QueryOut] = {}
        self.escalations: dict[str, EscalationRecord] = {}
        self.subject_flags: dict[str, int] = {}
        self.site_flags: dict[str, int] = {}
        self.sae_unescalated_watch: dict[str, int] = {}

    # ------------------------------------------------------------- queries
    def has_query(self, key: str) -> bool:
        return key in self.queries_raised

    def record_query(self, key: str, query: QueryOut) -> None:
        self.queries_raised.add(key)
        self.query_records[key] = query

    # --------------------------------------------------------- escalations
    def has_escalation(self, escalation_id: str) -> bool:
        return escalation_id in self.escalations

    def record_escalation(self, record: EscalationRecord) -> None:
        self.escalations[record.escalation_id] = record

    # --------------------------------------------------------------- flags
    def note_flags(self, subject_counts: dict[str, int],
                   site_counts: dict[str, int]) -> None:
        """Fold one cycle's per-subject/per-site finding counts into memory.

        `max`, not `+=`. See this module's docstring -- summing would make the
        second run of a cut disagree with the first.
        """
        for usubjid, count in subject_counts.items():
            if count > self.subject_flags.get(usubjid, 0):
                self.subject_flags[usubjid] = count
        for site, count in site_counts.items():
            if count > self.site_flags.get(site, 0):
                self.site_flags[site] = count

    def subject_flag_count(self, usubjid: str | None) -> int:
        return self.subject_flags.get(usubjid or "", 0)

    # ------------------------------------------------------- serialisation
    def to_snapshot(self) -> CrewMemorySnapshot:
        return CrewMemorySnapshot(
            cycle_number=self.cycle_number,
            queries_raised=sorted(self.queries_raised),
            query_records=dict(self.query_records),
            escalations=dict(self.escalations),
            subject_flags=dict(self.subject_flags),
            site_flags=dict(self.site_flags),
            sae_unescalated_watch=dict(self.sae_unescalated_watch),
        )

    def snapshot(self, path: str | Path | None = None) -> Path:
        """Write the whole of memory as JSON. Called after every cycle."""
        target = Path(path) if path is not None else self.snapshot_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_snapshot().model_dump(mode="json")
        # Write-then-rename: a crash mid-write leaves the previous good
        # snapshot in place rather than a truncated file that load() would
        # then have to reject.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(target)
        return target

    def load(self, path: str | Path | None = None) -> bool:
        """Restore memory from a snapshot.

        Returns True when state was restored. A missing or unreadable file
        leaves memory empty, logs a warning and returns False -- never raises
        (FR-15/NFR-2).
        """
        target = Path(path) if path is not None else self.snapshot_path
        if not target.exists():
            log.warning("no memory snapshot at %s - starting with empty memory", target)
            return False
        try:
            snap = CrewMemorySnapshot.model_validate_json(target.read_text())
        except Exception as exc:                                  # noqa: BLE001
            log.warning("memory snapshot at %s is unreadable (%s: %s) - "
                        "starting with empty memory", target, type(exc).__name__, exc)
            return False
        self.cycle_number = snap.cycle_number
        self.queries_raised = set(snap.queries_raised)
        self.query_records = dict(snap.query_records)
        self.escalations = dict(snap.escalations)
        self.subject_flags = dict(snap.subject_flags)
        self.site_flags = dict(snap.site_flags)
        self.sae_unescalated_watch = dict(snap.sae_unescalated_watch)
        return True

    def sizes(self) -> dict[str, int]:
        """Counts used by the idempotency check and the manual spot-check."""
        return {
            "queries_raised": len(self.queries_raised),
            "escalations": len(self.escalations),
            "subject_flags": len(self.subject_flags),
            "site_flags": len(self.site_flags),
            "sae_unescalated_watch": len(self.sae_unescalated_watch),
        }
