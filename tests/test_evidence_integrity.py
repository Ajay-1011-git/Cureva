"""Evidence integrity across the whole study — every code, every cut.

Why this exists. The public harness scores 10 questions and exercises 3 of the
11 finding codes. The hidden set is four times larger, covers every code, and
spans the mid-study protocol change. A 100/100 on the public set is therefore
consistent with eight detectors being badly broken, and says almost nothing
about whether a cited record really supports the claim made about it on data
nobody has looked at.

This sweeps all 11 codes at all 12 cuts -- 132 detector invocations -- and
checks every single evidence citation that comes back.

What it can and cannot establish, stated plainly so the result is not
oversold: it cannot prove the hidden set will pass, because correctness
against unseen answers is not provable from the practice study. What it does
establish is that every claim this system makes on the data it *can* see is
backed by a record that exists, is visible at the cut it was claimed at, and
belongs to the subject it was attributed to. Those are the failure modes that
turn into wrong answers on a hidden set, and they are checked by index lookup
rather than by re-running the logic under test, so a detector bug cannot hide
behind the same bug in the checker.
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Question
from stage1.atlas import Atlas, StudyGraph, protocol_section

DATA_DIR = os.environ.get("DATA_DIR", "hackathon-data")

CODES = ["HYS_LAW_CANDIDATE", "SAE_MISCODED", "AE_BEFORE_FIRST_DOSE",
         "DUPLICATE_SUBJECT", "VISIT_OUT_OF_WINDOW", "INCLUSION_VIOLATION",
         "EXCLUSION_VIOLATION", "PROHIBITED_CONMED", "DOSING_ERROR",
         "MISSING_EXPOSURE_RECORD", "LAB_UNIT_MISMATCH"]

# Codes no stage claims to detect from a single snapshot. Asking for one must
# produce an honest "not claimed", never a confident empty list -- the two are
# different answers and only one of them is true.
UNCLAIMED = ["SAE_UNESCALATED", "LAB_UNIT_CORRUPTION", "IMPLAUSIBLE_SITE_PATTERN",
             "LATE_DATA_ENTRY", "DOCUMENT_TAMPERED"]

CUTS = list(range(1, 13))

fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


graph = StudyGraph(DATA_DIR)
atlas = Atlas(graph)

print("=== Evidence integrity sweep: 11 codes x 12 cuts ===\n")

findings_total = 0
citations_total = 0
crashes: list[str] = []
dangling: list[str] = []          # cites a record not in the graph at all
not_yet_visible: list[str] = []   # cites a record from a future cut
bad_document: list[str] = []      # cites a document/section that does not exist
site_mismatch: list[str] = []     # finding.site disagrees with site_for(usubjid)
foreign_record: list[str] = []    # cites another subject's record
per_code = Counter()
per_cut_code: dict[int, Counter] = defaultdict(Counter)

for cut in CUTS:
    graph.build(cut)
    for code in CODES:
        q = Question(id=f"audit-{cut}-{code}", kind="finding",
                     text=f"All {code} at cut {cut}", params={"code": code}, cut=cut)
        try:
            answer = atlas.answer(q)
        except Exception as exc:                                  # noqa: BLE001
            crashes.append(f"{code}@{cut}: {type(exc).__name__}: {exc}")
            continue

        # Atlas.answer() is documented as never raising; a caught failure is
        # reported as a low-confidence empty answer instead. That is still a
        # failure for this audit's purposes, so look for it explicitly.
        if answer.text.startswith("could not answer"):
            crashes.append(f"{code}@{cut}: {answer.text[:90]}")
            continue

        per_code[code] += len(answer.findings)
        per_cut_code[cut][code] = len(answer.findings)
        findings_total += len(answer.findings)

        for finding in answer.findings:
            where = f"{code}@cut{cut}/{finding.usubjid}"

            if finding.usubjid:
                expected_site = graph.site_for(finding.usubjid)
                if finding.site != expected_site:
                    site_mismatch.append(
                        f"{where}: site={finding.site!r} but site_for()={expected_site!r}")

            for ref in finding.evidence:
                citations_total += 1

                if ref.document:
                    text = graph.document(ref.document) if ref.document else ""
                    if not text:
                        bad_document.append(f"{where}: document {ref.document!r} not loaded")
                    elif ref.section and not protocol_section(text, ref.section):
                        bad_document.append(
                            f"{where}: {ref.document} has no section {ref.section}")
                    continue

                record = graph.by_key.get((ref.domain.upper(), ref.usubjid, ref.seq))
                if record is None:
                    dangling.append(f"{where}: cites {ref.domain}:{ref.usubjid}:{ref.seq}, "
                                    f"which is not in the graph")
                    continue
                if record["_cut"] > cut:
                    not_yet_visible.append(
                        f"{where}: cites {ref.domain}:{ref.usubjid}:{ref.seq} from cut "
                        f"{record['_cut']}, which is not visible at cut {cut}")
                # A finding about one subject citing another subject's record is
                # how a plausible-looking wrong answer gets built. DUPLICATE_SUBJECT
                # legitimately spans two subjects, so it is exempt.
                if (finding.usubjid and ref.usubjid and ref.usubjid != finding.usubjid
                        and code != "DUPLICATE_SUBJECT"):
                    foreign_record.append(
                        f"{where}: cites {ref.usubjid}'s record")

print(f"  {findings_total} findings, {citations_total} evidence citations checked "
      f"across {len(CUTS) * len(CODES)} detector runs\n")

print("  findings per code (all cuts):")
for code in CODES:
    print(f"    {code:26} {per_code[code]}")
print()

check("Atlas.answer() never failed across the full matrix",
      not crashes, f"({len(crashes)} failures)" if crashes else "")
for c in crashes[:5]:
    print(f"        {c}")

check("every cited record exists in the graph",
      not dangling, f"({len(dangling)} dangling)" if dangling else "")
for d in dangling[:5]:
    print(f"        {d}")

check("no finding cites a record from a future cut",
      not not_yet_visible, f"({len(not_yet_visible)})" if not_yet_visible else "")
for d in not_yet_visible[:5]:
    print(f"        {d}")

check("every cited document and section exists",
      not bad_document, f"({len(bad_document)})" if bad_document else "")
for d in bad_document[:5]:
    print(f"        {d}")

check("every finding's site agrees with site_for(usubjid)",
      not site_mismatch, f"({len(site_mismatch)})" if site_mismatch else "")
for d in site_mismatch[:5]:
    print(f"        {d}")

check("no finding cites another subject's record",
      not foreign_record, f"({len(foreign_record)})" if foreign_record else "")
for d in foreign_record[:5]:
    print(f"        {d}")

silent = [c for c in CODES if per_code[c] == 0]
print(f"\n  codes silent across the whole study: {silent or 'none'}")

# A silent detector is the most dangerous thing in this system. It is
# indistinguishable, from the practice data alone, between "the study is clean"
# and "this code will score zero on the hidden set". So silence is not accepted
# on trust: each silent code must be shown to fire when its condition really
# exists, by constructing that condition.
for code in silent:
    if code != "LAB_UNIT_MISMATCH":
        check(f"{code} is silent and has no proof it can fire", False,
              "add an injection proof for it below")
        continue

    # The practice study's LB data carries only units that reference_ranges.csv
    # documents -- U/L and ukat/L for ALT/AST, each test's central unit for the
    # rest -- so there is genuinely nothing for this detector to find. Prove the
    # detector works anyway, by giving it something to find.
    from stage1.atlas import detect_lab_unit_mismatch
    probe = StudyGraph(DATA_DIR)
    probe.build(12)
    before = len(detect_lab_unit_mismatch(probe, None, None, 12))

    template = probe.records("LB", cut=12)[0]
    injected = dict(template)
    injected.update({"LBTESTCD": "ALT", "LBORRESU": "mmol/L", "LBORRES": "42",
                     "_seq": 999999, "_cut": 1})
    probe.by_domain["LB"].append(injected)
    probe.by_key[("LB", injected["USUBJID"], 999999)] = injected
    probe.by_usubjid_domain.setdefault((injected["USUBJID"], "LB"), []).append(injected)

    after = detect_lab_unit_mismatch(probe, None, None, 12)
    check(f"{code} is silent because the study is clean, not because it is broken",
          before == 0 and len(after) == 1,
          f"(0 findings on the real data; 1 after injecting one ALT in mmol/L)")
    check(f"{code}'s injected finding cites the offending record",
          bool(after) and any(e.seq == 999999 for e in after[0].evidence))

check("every code that is silent has a proof it can fire",
      set(silent) <= {"LAB_UNIT_MISMATCH"},
      f"(silent: {silent})")

# ---------------------------------------------------------------- honesty
print()
graph.build(12)
honest = True
for code in UNCLAIMED:
    a = atlas.answer(Question(id=f"u-{code}", kind="finding", text="t",
                              params={"code": code}, cut=12))
    if a.answer != [] or "does not claim" not in a.text:
        honest = False
        print(f"        {code}: {a.text[:100]}")
check("an unclaimed code says so, rather than returning a confident empty list",
      honest, f"({len(UNCLAIMED)} codes checked)")

# ------------------------------------------------------------ determinism
graph.build(9)
first = atlas.answer(Question(id="d1", kind="finding", text="t",
                              params={"code": "VISIT_OUT_OF_WINDOW"}, cut=9))
second = atlas.answer(Question(id="d2", kind="finding", text="t",
                               params={"code": "VISIT_OUT_OF_WINDOW"}, cut=9))
check("the same question asked twice returns the identical finding set",
      [f.fingerprint() for f in first.findings] == [f.fingerprint() for f in second.findings],
      f"({len(first.findings)} findings)")

# ------------------------------------------- the mid-study protocol change
v1 = per_cut_code[1]["VISIT_OUT_OF_WINDOW"]
v3 = per_cut_code[12]["VISIT_OUT_OF_WINDOW"]
check("the protocol change actually changes the answer",
      graph.protocol_version_at(1) == 1 and graph.protocol_version_at(12) == 3 and v3 > v1,
      f"(cut 1/v1: {v1} findings, cut 12/v3: {v3} findings)")

print("\n" + ("ALL EVIDENCE INTEGRITY CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
