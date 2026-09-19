"""T3.2 VERIFY — `WatchMemory`'s snapshot discipline and its idempotency.

Two things are proved here, and the second is the one the Stage 3 ground-truth
table specifically asks for:

* NFR-2: a missing or corrupt snapshot starts empty and logs, never raises --
  `CrewMemory`'s exact precedent.
* FR-3: every stateful primitive is idempotent under a repeated cut. Stage 2
  shipped this bug twice (a summed counter; a key on cycle-count instead of
  cut), so each structure is exercised against a repeat rather than assumed
  clean.

Run: .venv/bin/python tests/test_t3_2_memory.py
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage3.memory import SupersededFinding, WatchMemory, lab_series_key

logging.basicConfig(level=logging.CRITICAL)   # the warnings are the point, but not here

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


tmp = Path(tempfile.mkdtemp(prefix="cureva-t32-"))
GLUC = lab_series_key("GLUC")

print("=" * 72)
print("NFR-2 — a missing or corrupt snapshot starts empty and logs, never raises")
print("=" * 72)
check("missing file -> load() False, no exception",
      WatchMemory(tmp / "nope" / "missing.json").load() is False)

bad = tmp / "bad.json"
for label, content in [("truncated", '{"trend_history": {"S01": {"site":'),
                       ("schema-invalid", '{"trend_history": 12345}'),
                       ("empty", "")]:
    bad.write_text(content)
    m = WatchMemory(bad)
    check(f"{label} file -> load() False, no exception", m.load() is False)
    check(f"  memory is empty after the failed {label} load",
          m.sizes()["finding_first_cut"] == 0)

print()
print("=" * 72)
print("FR-3 — every primitive is idempotent under a repeated cut")
print("=" * 72)


def populate(mem: WatchMemory, times: int) -> WatchMemory:
    for _ in range(times):
        mem.observe("S04", GLUC, 8, 8.25)
        mem.note_finding("F-abc", 8)
        mem.observe_document("lab-manual", 8, "text")
        mem.note_cut(8)
        mem.record_superseded(SupersededFinding(
            finding_id="F-x", first_raised_cut=3, superseded_at_cut=5, reason="r"))
    return mem


thrice = populate(WatchMemory(tmp / "a.json"), 3)
once = populate(WatchMemory(tmp / "b.json"), 1)
check("walking the same cut 3x == walking it once", thrice.sizes() == once.sizes(),
      str(thrice.sizes()))
check("  the series holds one point for that cut, not three",
      len(thrice.trend_history["S04"].series[GLUC]) == 1)
check("  superseded holds one entry, not three", len(thrice.superseded) == 1)
check("  cuts_walked holds one entry, not three", thrice.cuts_walked == [8])

out_of_order = WatchMemory(tmp / "c.json")
for cut in (9, 4, 7):
    out_of_order.note_finding("F-y", cut)
check("note_finding uses min(), so an out-of-order walk still gives the earliest cut",
      out_of_order.finding_first_cut["F-y"] == 4,
      f"got {out_of_order.finding_first_cut['F-y']}")

bounded = WatchMemory(tmp / "d.json")
history = bounded.site_history("S04")
for cut, value in [(6, 140.0), (7, 136.55), (8, 8.25), (9, 7.95)]:
    history.observe(GLUC, cut, value)
seen = history.values_upto(GLUC, 7)
check("values_upto() is bounded, so cut 7 never reads a value left by cut 8",
      seen == [(6, 140.0), (7, 136.55)], str(seen))

period = WatchMemory(tmp / "e.json")
period.note_finding("F-z", 1)
period.tokens_spent_this_period, period.rollouts_run_this_period = 5000, 400
period.begin_period()
check("begin_period() resets the token counter", period.tokens_spent_this_period == 0)
check("begin_period() resets the rollout counter", period.rollouts_run_this_period == 0)
check("begin_period() keeps cross-cut knowledge", period.finding_first_cut == {"F-z": 1})

print()
print("=" * 72)
print("TNFR-4 — a restart resumes from the snapshot exactly")
print("=" * 72)
src = WatchMemory(tmp / "f.json")
src.observe("S11", GLUC, 6, 118.10)
src.note_finding("F-q", 2)
src.observe_document("lab-manual_v3", 8, "addendum")
src.note_cut(6)
src.record_superseded(SupersededFinding(
    finding_id="F-s", escalation_id="ESC-1", first_raised_cut=3,
    superseded_at_cut=5, reason="corrected", cause="correction"))
src.pending_queue["ESC-7"] = 9
src.tokens_spent_this_period = 1234
src.snapshot()

dst = WatchMemory(tmp / "f.json")
check("load() returns True on a good snapshot", dst.load() is True)
check("  sizes round-trip exactly", dst.sizes() == src.sizes())
check("  int cut keys survive JSON (they serialise as strings)",
      dst.trend_history["S11"].at(GLUC, 6) == 118.10)
check("  document digests survive",
      dst.document_digest_before("lab-manual_v3", 12)
      == (8, src.document_digests["lab-manual_v3"][8]))
check("  pending_queue survives", dst.pending_queue == {"ESC-7": 9})
check("  the supersession's cause survives", dst.superseded[0].cause == "correction")
check("  period spend survives a restart mid-period",
      dst.tokens_spent_this_period == 1234)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
