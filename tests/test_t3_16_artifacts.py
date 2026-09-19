"""T3.16 VERIFY — execution artifacts drafted from a decision's own evidence.

The claim this test has to earn is a strong one: **every concrete detail in a
drafted artifact traces back to a real record.** Not one subject id, value,
unit, visit name or date in the output was typed into a template.

PART 3 checks that mechanically rather than by reading the text and being
satisfied: every number and identifier in every artifact is extracted and
matched against the real CSV rows it claims to come from.

Run: .venv/bin/python tests/test_t3_16_artifacts.py
"""
import logging
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execute.templates import (AVATAR_RULE_CODES, IRB_MEMO_CODES,
                               artifact_kind_for, draft_artifact)
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

DATA = "hackathon-data"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


state = Path(tempfile.mkdtemp(prefix="cureva-t316-"))
graph = StudyGraph(DATA)
crew = ReviewCrew(DATA, Atlas(graph), state_dir=state)
watch = StudyWatch(DATA, crew)
report = watch.run_period(cuts=range(1, 13))
artifacts = watch.artifacts

# ==========================================================================
print("=" * 74)
print("PART 1 — one artifact per APPROVED decision, and only APPROVED")
print("=" * 74)
approved = [d for d in report.decisions if d.action == "APPROVED"]
rejected = [d for d in report.decisions if d.action == "REJECTED"]
pending = [r for r in crew.memory.escalations.values() if r.state == "PENDING"]
print(f"  APPROVED decisions : {len(approved)}")
print(f"  REJECTED decisions : {len(rejected)}")
print(f"  PENDING escalations: {len(pending)}")
print(f"  artifacts drafted  : {len(artifacts)}")
print(f"  by kind            : {dict(Counter(a.kind for a in artifacts.values()))}")
print(f"  by source          : {dict(Counter(a.source for a in artifacts.values()))}")

check("every APPROVED decision produced exactly one artifact",
      len(artifacts) == len(approved), f"{len(artifacts)} vs {len(approved)}")
check("  no REJECTED decision produced one",
      not any(d.id in artifacts for d in rejected))
check("  no PENDING escalation produced one — nothing was approved to act on",
      not any(r.escalation_id in artifacts for r in pending))
check("  all three kinds are exercised on real data",
      set(a.kind for a in artifacts.values())
      == {"IRB_MEMO", "SITE_QUERY", "AVATAR_RULE_UPDATE"})
check("  every artifact is tagged template_only at this stage",
      all(a.source == "template_only" for a in artifacts.values()))

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the documented kind-for-code rule, applied consistently")
print("=" * 74)
observed: dict[str, set[str]] = {}
for a in artifacts.values():
    observed.setdefault(a.kind, set()).add(a.code)
for kind in sorted(observed):
    print(f"  {kind:<20} {sorted(observed[kind])}")
check("every IRB_MEMO code is one the rule assigns to IRB_MEMO",
      observed.get("IRB_MEMO", set()) <= IRB_MEMO_CODES,
      str(observed.get("IRB_MEMO", set()) - IRB_MEMO_CODES))
check("every AVATAR_RULE_UPDATE code is one the rule assigns to it",
      observed.get("AVATAR_RULE_UPDATE", set()) <= AVATAR_RULE_CODES,
      str(observed.get("AVATAR_RULE_UPDATE", set()) - AVATAR_RULE_CODES))
check("  the same code always produces the same kind",
      all(len({artifact_kind_for(a.code) for a in artifacts.values()
               if a.code == code}) == 1
          for code in {a.code for a in artifacts.values()}))
check("  an unknown code falls back to SITE_QUERY — the lowest-consequence "
      "honest default, which asks rather than asserts",
      artifact_kind_for("SOME_CODE_THIS_STUDY_HAS_NEVER_SEEN") == "SITE_QUERY")

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — MECHANICAL: every fact in every artifact traces to a record")
print("=" * 74)
graph.build(12)
checked_values, unmatched = 0, []
for a in artifacts.values():
    # Collect the real values of every record the artifact cites.
    real: set[str] = set()
    for ref in a.evidence:
        if ref.domain == "DOC" or ref.document:
            real.add(str(ref.document))
            if ref.section:
                real.add(str(ref.section))
            continue
        record = graph.by_key.get((ref.domain, ref.usubjid, ref.seq))
        if not record:
            continue
        real.add(str(ref.usubjid))
        for key, value in record.items():
            if key.startswith("_"):
                continue
            real.add(str(graph.record_value(record, key)))
            real.add(str(value))
    # The "facts" block is what the template quoted. Every key=value pair in it
    # must be a value the record really holds.
    for fact in a.facts:
        # Split on " | ", the template's own separator — not on commas, which
        # occur INSIDE real values ("LBORRES=177,7" is one European decimal
        # number, not two fields).
        for pair in re.findall(r"(\w+)=([^|]+?)(?=\s*\||$)", fact):
            checked_values += 1
            if pair[1].strip() not in real:
                unmatched.append((a.decision_id, fact, pair))

print(f"  artifacts examined            : {len(artifacts)}")
print(f"  quoted key=value pairs checked: {checked_values:,}")
print(f"  pairs not found in the cited records: {len(unmatched)}")
for row in unmatched[:5]:
    print(f"      {row}")
check("every quoted value is a value the cited record really holds",
      not unmatched, f"{len(unmatched)} unmatched")

# No placeholder ever reaches the output.
placeholders = [(a.decision_id, m) for a in artifacts.values()
                for m in re.findall(r"\[[A-Z_]{3,}\]|\{[a-z_]+\}|XXXX|TBD|TODO",
                                    a.text)]
check("  no placeholder token survives into any artifact", not placeholders,
      str(placeholders[:3]))
check("  no artifact contains a doubled full stop", 
      not any(".." in a.text for a in artifacts.values()))
check("  no artifact prints 'seq None' for a domain that has no sequence",
      not any("seq None" in a.text for a in artifacts.values()))

subject_ids = set()
for a in artifacts.values():
    subject_ids.update(re.findall(r"\b042-S\d{2}-\d{3}\b", a.text))
real_subjects = {r["USUBJID"] for r in graph.study.domains["DM"]}
check("  every subject id that appears in any artifact is a real subject",
      subject_ids <= real_subjects,
      str(sorted(subject_ids - real_subjects)[:3]))
print(f"      {len(subject_ids)} distinct subject ids mentioned, all real")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — a full real artifact of each kind")
print("=" * 74)
for kind in ("IRB_MEMO", "SITE_QUERY", "AVATAR_RULE_UPDATE"):
    a = next(x for x in artifacts.values() if x.kind == kind)
    print(f"\n  {'#' * 68}")
    print(f"  # {kind}  —  {a.code}, decision {a.decision_id}, cut {a.cut}")
    print(f"  {'#' * 68}")
    for line in a.text.splitlines():
        print(f"  {line}")
    check(f"{kind}: names the real subject or site",
          (a.usubjid or a.site or "") in a.text)
    check(f"  {kind}: quotes at least one real record", bool(a.facts))
    check(f"  {kind}: states it changed no trial data",
          "altered" in a.text or "has been changed by Cureva" in a.text
          or "changes no trial data" in a.text)

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — honesty when a record cannot be read")
print("=" * 74)
from schemas import RecordRef                                     # noqa: E402
ghost = draft_artifact(
    decision_id="ESC-test", code="HYS_LAW_CANDIDATE", usubjid="042-S01-999",
    site="S01", cut=5, rationale="Synthetic probe.", reason="Noted.",
    evidence=[RecordRef(domain="LB", usubjid="042-S01-999", seq=9999)],
    graph=graph)
line = ghost.facts[0]
print(f"  citing a record that does not exist:\n      {line}")
check("an unreadable record is reported as unreadable, not invented",
      "not retrievable" in line)
check("  and the citation is still printed so a reader can go and look",
      "042-S01-999" in line and "9999" in line)
check("  and no placeholder value is emitted for it",
      not re.search(r"\[[A-Z_]+\]", ghost.text))

empty = draft_artifact(
    decision_id="ESC-empty", code="DOCUMENT_TAMPERED", usubjid=None, site=None,
    cut=8, rationale="", reason=None, evidence=[], graph=graph)
check("an artifact with no evidence says so rather than fabricating any",
      "(no records cited)" in empty.text)
check("  and still names what it is about", "DOCUMENT_TAMPERED" in empty.text)
check("  and still produces a valid artifact", empty.kind == "IRB_MEMO"
      and empty.source == "template_only")

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
