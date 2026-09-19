"""T3.24 VERIFY — the Problem 3 submission artifacts.

The claim that matters is the one about the decision log: **every explanation
in it is a real `explain()` result read from the trace on disk**, not a
plausible-looking sentence written into a JSON file.

PART 2 checks that the hard way. It re-reads the trace file, finds the lines
for a sampled decision, and compares them field by field against what the log
carries — including that the COUNTS match, which is how a real inconsistency
was found: the generator's own idempotency check was walking the period two
further times against the same state directory, so the trace grew after the
log was written and the log cited 9 lines for a decision the file then had 23
of. The measurement was changing what it measured.

Run: .venv/bin/python tests/test_t3_24_artifacts.py
"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


# ==========================================================================
print("=" * 74)
print("PART 1 — every artifact exists and is non-empty")
print("=" * 74)
ARTIFACTS = [
    ("Surveillance report", "stage3_surveillance_report.md"),
    ("Decision log", "stage3_decision_log.json"),
    ("Public score summary", "stage3_public.json"),
    ("Solution Design", "docs/stage3-solution-design.md"),
    ("Deck outline", "docs/stage3-deck-outline.md"),
    ("Demo video checklist", "docs/demo-video-checklist.md"),
    ("Screenshots README", "docs/screenshots/README.md"),
    ("Forecast chart render", "docs/screenshots/forecast-fan-chart.png"),
    ("Contract audit", "docs/stage3-contract-audit.md"),
]
for label, rel in ARTIFACTS:
    path = REPO / rel
    size = path.stat().st_size if path.exists() else 0
    print(f"      {rel:<44} {size:>10,} bytes")
    check(f"{label} exists and is non-empty", path.exists() and size > 0)

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — every decision log entry carries a REAL explanation")
print("=" * 74)
log = json.loads((REPO / "stage3_decision_log.json").read_text())
counts, entries = log["counts"], log["entries"]
print(f"  period        : {log['period']}")
print(f"  ENTRY COUNT   : {counts['decisions']}")
print(f"  with a real explanation : {counts['with_real_explanation']}")
print(f"  WITHOUT one             : {counts['without_explanation']}")
print(f"  with paperwork          : {counts['with_drafted_artifact']}")
print(f"  with forecast context   : {counts['with_forecast_context']}")
print(f"  escalation states       : {counts['escalation_states']}")

check("the log's entry count matches its own header",
      len(entries) == counts["decisions"], f"{len(entries)}")
check("EVERY entry has a real explanation — none missing",
      counts["without_explanation"] == 0 and
      all(e["explanation"]["evidence_lines"] for e in entries))
check("  every explanation's id matches its decision's id",
      all(e["explanation"]["decision_id"] == e["decision"]["id"] for e in entries))
check("  every explanation carries a non-empty 'what' and 'why'",
      all(e["explanation"]["what"].strip() and e["explanation"]["why"].strip()
          for e in entries))
check("  none is flagged inconsistent with its own trace",
      all(e["explanation"]["consistent_with_trace"] for e in entries))
check("  none quotes the review-page placeholder as what happened",
      not [e for e in entries
           if "decided on the review page" in e["explanation"]["what"]])
print(f"  total trace lines carried: "
      f"{sum(len(e['explanation']['evidence_lines']) for e in entries):,}")

print("\n  cross-checking sampled entries against the trace file on disk:")
trace_path = REPO / log["trace_files"][0]
check(f"the trace file the log names really exists", trace_path.exists(),
      str(trace_path))
raw_lines = [json.loads(l) for l in trace_path.read_text().splitlines() if l.strip()]
print(f"      {trace_path} — {len(raw_lines):,} lines")

random.seed(11)
for entry in random.sample(entries, 5):
    did = entry["decision"]["id"]
    on_disk = [r for r in raw_lines if r.get("escalation_id") == did]
    rendered = entry["explanation"]["evidence_lines"]
    same_count = len(on_disk) == len(rendered)
    verbatim = all(str(raw[f]) in line
                   for raw, line in zip(on_disk, rendered)
                   for f in ("cut", "cycle", "node", "decision_type", "summary"))
    print(f"      {did}: log {len(rendered):>2} lines, file {len(on_disk):>2} lines"
          f" — {'match' if same_count and verbatim else 'MISMATCH'}")
    check(f"  {did}: line count matches the file exactly", same_count,
          f"{len(rendered)} vs {len(on_disk)}")
    check(f"  {did}: every field is verbatim from the file", verbatim)

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — the surveillance report is the graded object's own markdown")
print("=" * 74)
report_md = (REPO / "stage3_surveillance_report.md").read_text()
print(f"  {len(report_md):,} chars, {len(report_md.splitlines())} lines")
for heading in ("What this period found", "Which sites need attention first",
                "Escalations and the human gate",
                "Findings that are no longer current", "Where sites are heading",
                "Paperwork drafted", "what it would give up under pressure"):
    check(f"has the '{heading}' section", heading in report_md)
for site, what in (("S04", "collapsed by a factor"), ("S11", "too uniform"),
                   ("S08", "well after the events"),
                   ("lab-manual_v3", "attempting to steer")):
    check(f"  names the real {site} finding", site in report_md and what in report_md)
check("  states that the escalation timing is simulated",
      "is Cureva's own policy, not the organiser's behaviour" in report_md)
check("  states that silence is never approval",
      "never treated as approval" in report_md)

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — the Solution Design fits in three pages")
print("=" * 74)
design = (REPO / "docs/stage3-solution-design.md").read_text()
words = len(design.split())
print(f"  words {words:,} · lines {len(design.splitlines())} · {len(design):,} chars")
for per_page in (450, 500, 600):
    print(f"      at {per_page} words/page -> {words / per_page:.1f} pages")
check("within 3 pages even at a conservative 450 words/page",
      words / 450 <= 3.0, f"{words / 450:.1f} pages")
for topic, needle in (("time budgeting", "Time and token budgeting"),
                      ("escalation policy", "slow, unreliable reviewer"),
                      ("adversarial detection", "Adversarial detection"),
                      ("degradation behaviour", "Degradation behaviour"),
                      ("trade-offs and limitations", "Trade-offs and limitations"),
                      ("who did what", "Who did what")):
    check(f"  covers {topic}", needle in design)
check("  states the simulated escalation timing as a limitation",
      "escalation timing is simulated" in design)
check("  states the new-domain-file limitation",
      "new domain *file* is not absorbed" in design)

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — deck outline and demo checklist")
print("=" * 74)
deck = (REPO / "docs/stage3-deck-outline.md").read_text()
slides = [l for l in deck.splitlines() if l.startswith("**") and "·" in l]
print(f"  deck: {len(slides)} numbered slides, {len(deck.split()):,} words")
check("the deck has 12 slides", len(slides) == 12, str(len(slides)))
check("  it covers all three problems",
      all(f"Problem {n}" in deck for n in (1, 2, 3)))
check("  it is written for a clinical judge as well",
      "Clinical framing" in deck or "clinical" in deck.lower())
check("  it ends on the limitations",
      "would not claim" in deck)

checklist = (REPO / "docs/demo-video-checklist.md").read_text()
boxes = checklist.count("- [ ]")
print(f"  checklist: {boxes} checkboxes, {len(checklist.split()):,} words")
check("the demo checklist is a real checklist", boxes >= 25, str(boxes))
check("  it covers the live-demo-fails case", "If the live demo fails" in checklist)
check("  it requires the trace to be shown on camera",
      "JSONL" in checklist and "grep" in checklist)

shots = (REPO / "docs/screenshots/README.md").read_text()
check("the screenshots README is honest about what was not captured",
      "No page screenshots" in shots and "had no browser" in shots)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails[:5]}")
sys.exit(1 if fails else 0)
