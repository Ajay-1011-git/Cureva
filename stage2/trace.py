"""The JSONL trace — written live, one line per decision.

Two properties this file guarantees, both load-bearing downstream:

* **Live, not reconstructed** (FR-17). Each entry is appended and flushed at
  the moment the decision is made. `run_cycle()` crashing halfway leaves a file
  containing every decision taken up to that point -- which is what makes the
  trace evidence rather than a summary. T2.10 verifies this by interrupting a
  cycle and reading the file back.
* **Format-final** (PRD G5). Stage 3's `explain()` reads this format verbatim.
  The shape lives in `stage2/models.py:TraceEntry` and does not change after
  this stage.

`flush()` plus `os.fsync()` on every line is deliberately more than buffering
would need. The cost is a few hundred microseconds per decision, against a
cycle that spends most of its time in detectors; the benefit is that "the
process died" and "the decision was never made" stay distinguishable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from schemas import RecordRef

from stage2.models import TraceEntry

log = logging.getLogger("cureva.stage2.trace")

DEFAULT_TRACE_DIR = Path("state/trace")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TraceWriter:
    """Append-only JSONL writer, one line per `TraceEntry`."""

    def __init__(self, path: str | Path | None = None,
                 trace_dir: str | Path = DEFAULT_TRACE_DIR):
        if path is None:
            path = Path(trace_dir) / "cycle_trace.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh: IO[str] | None = None
        # This cycle's entries, kept so EXECUTE can put them in the
        # ReviewReport. It is a copy of what is already on disk, never the
        # source of truth, and never the thing that gets written.
        self.current_cycle: list[TraceEntry] = []

    # ------------------------------------------------------------ lifecycle
    def _handle(self) -> IO[str]:
        if self._fh is None or self._fh.closed:
            self._fh = self.path.open("a", encoding="utf-8")
        return self._fh

    def begin_cycle(self) -> None:
        """Clear the per-cycle buffer. Does not touch the file."""
        self.current_cycle = []

    def close(self) -> None:
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.close()
            self._fh = None

    # --------------------------------------------------------------- write
    def write(self, *, cycle: int, cut: int, protocol_version: int,
              node: str, decision_type: str, summary: str,
              finding_id: str | None = None, escalation_id: str | None = None,
              evidence: list[RecordRef] | None = None,
              duration_ms: int = 0) -> TraceEntry:
        """Record one decision, on disk, now."""
        entry = TraceEntry(
            trace_id=uuid.uuid4().hex[:16],
            cycle=cycle,
            cut=cut,
            protocol_version=protocol_version,
            node=node,                       # type: ignore[arg-type]
            decision_type=decision_type,     # type: ignore[arg-type]
            finding_id=finding_id,
            escalation_id=escalation_id,
            evidence=list(evidence or []),
            summary=summary,
            timestamp=utc_now(),
            duration_ms=duration_ms,
        )
        line = json.dumps(entry.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            try:
                fh = self._handle()
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            except Exception as exc:                              # noqa: BLE001
                # A trace that cannot be written must not take the cycle down
                # with it -- but it is never swallowed silently either, because
                # FR-18 treats a decision with no trace line as not having
                # happened, and that has to be visible.
                log.error("trace write failed (%s: %s) for %s/%s",
                          type(exc).__name__, exc, node, decision_type)
            self.current_cycle.append(entry)
        return entry

    # ---------------------------------------------------------------- read
    def cycle_dicts(self) -> list[dict]:
        """This cycle's entries as plain dicts, for `ReviewReport.trace`."""
        return [e.model_dump(mode="json") for e in self.current_cycle]

    def read_all(self) -> list[dict]:
        """Every entry on disk. Used by the tests and by Stage 3 later."""
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn final line means the process died mid-write. That is
                # information, not corruption to hide.
                log.warning("trace file %s ends in a partial line", self.path)
        return out
