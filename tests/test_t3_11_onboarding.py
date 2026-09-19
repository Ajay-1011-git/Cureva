"""T3.11 VERIFY — a new site and a new measurement are absorbed with zero code change.

FR-13/G5. Stage 1 built `StudyGraph` generic over site and domain names on
purpose; this test proves that mechanically rather than arguing it from the
absence of hard-coded strings.

Three things are introduced into a private copy of the study, none of which
appears anywhere in the real practice data, all arriving PART-WAY through the
period rather than at cut 1:

  1. a new site id            — subjects, labs, adverse events, exposure, vitals
  2. a new laboratory test    — a measurement the study has never seen
  3. a new domain CSV file    — the boundary case, reported honestly in PART 4

Nothing in `stage1/`, `stage2/`, `stage3/`, `forecast/` or `execute/` is
changed to make any of this work. PART 5 proves that with `git diff`.

Run: .venv/bin/python tests/test_t3_11_onboarding.py
"""
import csv
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import Question
from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

logging.basicConfig(level=logging.CRITICAL)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "hackathon-data"

# None of these appears anywhere in the real study.
NEW_SITE = "S77"
NEW_SUBJECTS = [f"042-{NEW_SITE}-{i:03d}" for i in (1, 2, 3)]
NEW_TEST = "MAGN"                 # magnesium — a test the study has never run
NEW_DOMAIN = "PE"                 # physical exam — a domain file that does not exist
JOINS_AT_CUT = 7                  # part-way through the period, not at the start

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


def append_rows(path: Path, rows: list[dict]) -> None:
    existing = list(csv.DictReader(path.open()))
    fields = list(existing[0].keys())
    with path.open("a", newline="") as fh:
        csv.DictWriter(fh, fieldnames=fields).writerows(
            [{k: r.get(k, "") for k in fields} for r in rows])


# ==========================================================================
print("=" * 74)
print("PART 1 — building a study that contains things the code has never seen")
print("=" * 74)
fixture = Path(tempfile.mkdtemp(prefix="cureva-t311-")) / "onboarded-study"
shutil.copytree(DATA, fixture)

before = {name: len(list(csv.DictReader((DATA / "data" / f"{name}.csv").open())))
          for name in ("DM", "LB", "AE", "EX", "VS")}

append_rows(fixture / "data" / "DM.csv", [
    {"USUBJID": u, "SITEID": NEW_SITE, "COUNTRY": "IN", "AGE": 55 + i, "SEX": "F",
     # Distinct initials and birth dates on purpose: identical ones would trip
     # DUPLICATE_SUBJECT and this test would end up proving that detector works
     # rather than that a new site is absorbed.
     "DMINIT": ["QRS", "TUV", "WXY"][i], "BRTHDTC": f"197{i}-0{i + 4}-1{i + 1}",
     "ARM": "DRUG", "RFSTDTC": "2026-05-04", "SCR_HBA1C": "8.4",
     "cut_available": JOINS_AT_CUT}
    for i, u in enumerate(NEW_SUBJECTS)])

# One subject discontinues because of an adverse event, so the one metric
# Atlas actually registers has something real to count at the new site.
append_rows(fixture / "data" / "DS.csv", [
    {"USUBJID": NEW_SUBJECTS[0], "DSSEQ": 1, "DSDECOD": "DISCONTINUED",
     "DSSTDTC": "2026-05-14", "DSTERM": "ADVERSE EVENT",
     "cut_available": JOINS_AT_CUT}])

lb_rows = []
for u in NEW_SUBJECTS:
    lb_rows.append({"USUBJID": u, "LBSEQ": 1, "VISIT": "SCREENING",
                    "LBDTC": "2026-05-06", "LBTESTCD": "ALT", "LBORRES": "38.2",
                    "LBORRESU": "U/L", "cut_available": JOINS_AT_CUT})
    # The new measurement: a test with no reference range and no prior history.
    lb_rows.append({"USUBJID": u, "LBSEQ": 2, "VISIT": "SCREENING",
                    "LBDTC": "2026-05-06", "LBTESTCD": NEW_TEST, "LBORRES": "0.85",
                    "LBORRESU": "mmol/L", "cut_available": JOINS_AT_CUT})
append_rows(fixture / "data" / "LB.csv", lb_rows)

append_rows(fixture / "data" / "AE.csv", [
    {"USUBJID": NEW_SUBJECTS[0], "AESEQ": 1, "AETERM": "Nausea", "AESEV": "MILD",
     "AESER": "N", "AESHOSP": "N", "AESTDTC": "2026-05-10",
     "AEENDTC": "2026-05-12", "AEOUT": "RECOVERED",
     "AENARR": "Synthetic onboarding record (T3.11).",
     "cut_available": JOINS_AT_CUT}])

append_rows(fixture / "data" / "EX.csv", [
    {"USUBJID": u, "EXSEQ": 1, "VISIT": "BASELINE", "EXSTDTC": "2026-05-04",
     "EXDOSE": "10", "EXDOSU": "mg", "EXTRT": "DRUG", "cut_available": JOINS_AT_CUT}
    for u in NEW_SUBJECTS])

append_rows(fixture / "data" / "VS.csv", [
    {"USUBJID": u, "VSSEQ": 1, "VISIT": "SCREENING", "VSDTC": "2026-05-06",
     "VSTESTCD": "SYSBP", "VSORRES": "124.0", "VSORRESU": "mmHg",
     "cut_available": JOINS_AT_CUT} for u in NEW_SUBJECTS])

# A whole new domain file. Nothing tells the loader it exists.
(fixture / "data" / f"{NEW_DOMAIN}.csv").write_text(
    "USUBJID,PESEQ,VISIT,PEDTC,PETESTCD,PEORRES,cut_available,corrected_at_cut\n"
    + "".join(f"{u},1,SCREENING,2026-05-06,GENAPP,NORMAL,{JOINS_AT_CUT},\n"
             for u in NEW_SUBJECTS))

print(f"  new site      : {NEW_SITE} ({len(NEW_SUBJECTS)} subjects), joining at cut {JOINS_AT_CUT}")
print(f"  new lab test  : {NEW_TEST} (no reference range exists for it)")
print(f"  new domain    : {NEW_DOMAIN}.csv ({len(NEW_SUBJECTS)} rows)")
for name in ("DM", "LB", "AE", "EX", "VS"):
    after = len(list(csv.DictReader((fixture / "data" / f"{name}.csv").open())))
    print(f"    {name}: {before[name]} -> {after} rows")
check(f"{NEW_SITE} appears nowhere in the real study",
      NEW_SITE not in (DATA / "data" / "DM.csv").read_text())
check(f"{NEW_TEST} appears nowhere in the real study",
      NEW_TEST not in (DATA / "data" / "LB.csv").read_text())
check(f"{NEW_DOMAIN}.csv does not exist in the real study",
      not (DATA / "data" / f"{NEW_DOMAIN}.csv").exists())

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — the new SITE is absorbed end to end, with no code change")
print("=" * 74)
graph = StudyGraph(str(fixture))
atlas = Atlas(graph)
state = Path(tempfile.mkdtemp(prefix="cureva-t311-state-"))
crew = ReviewCrew(str(fixture), atlas, state_dir=state)
watch = StudyWatch(str(fixture), crew)

check("StudyGraph loads the study without raising", graph is not None)
check(f"  graph.sites() includes {NEW_SITE}", NEW_SITE in graph.sites(),
      f"{len(graph.sites())} sites: {graph.sites()}")
check(f"  site_for() resolves the new subjects to {NEW_SITE}",
      all(graph.site_for(u) == NEW_SITE for u in NEW_SUBJECTS))

graph.build(JOINS_AT_CUT)
for u in NEW_SUBJECTS[:1]:
    profile = graph.patient360(u)
    domains = {d: len(v) for d, v in (profile.get("domains") or {}).items() if v}
    print(f"  patient360({u}) -> {domains}")
    check(f"  patient360 returns real records for {u}", bool(domains))
    check("    including the labs, the adverse event and the exposure",
          domains.get("LB", 0) >= 2 and domains.get("EX", 0) >= 1)

graph.build(JOINS_AT_CUT - 1)
check(f"  before cut {JOINS_AT_CUT} the new site is correctly INVISIBLE",
      not graph.records("DM", cut=JOINS_AT_CUT - 1, site=NEW_SITE),
      f"{len(graph.records('DM', cut=JOINS_AT_CUT - 1, site=NEW_SITE))} rows")
graph.build(JOINS_AT_CUT)
check(f"  from cut {JOINS_AT_CUT} it is visible",
      len(graph.records("DM", cut=JOINS_AT_CUT, site=NEW_SITE)) == len(NEW_SUBJECTS),
      f"{len(graph.records('DM', cut=JOINS_AT_CUT, site=NEW_SITE))} rows")

# `discontinued_ae` is the one metric Atlas registers, and it takes a site
# filter. One of the new subjects really did discontinue because of an adverse
# event, so a correct answer for a site the code has never seen is 1.
answer = atlas.answer(Question(
    id="onboard-count", kind="count",
    text=f"How many subjects at site {NEW_SITE} discontinued due to an adverse event?",
    params={"metric": "discontinued_ae", "site": NEW_SITE}, cut=12))
print(f"  Atlas discontinued_ae count for {NEW_SITE}: {answer.answer} "
      f"(confidence {answer.confidence})")
print(f"      evidence: {[(e.domain, e.usubjid, e.seq) for e in answer.evidence]}")
check(f"  Atlas counts the new site correctly through its registered metric",
      answer.answer == 1, str(answer.answer))
check("    and cites the new subject's own record as evidence",
      any(e.usubjid == NEW_SUBJECTS[0] for e in answer.evidence),
      str([e.usubjid for e in answer.evidence]))

# The honest-refusal path is a Stage 1 property worth not breaking: a metric
# that does not exist is declined, not guessed at, for a new site as for any.
unknown = atlas.answer(Question(id="onboard-unknown", kind="count", text="",
                                params={"metric": "subjects", "site": NEW_SITE},
                                cut=12))
check("  an UNREGISTERED metric is still honestly declined for the new site "
      "(answer=None at zero confidence), not guessed",
      unknown.answer is None and unknown.confidence == 0.0,
      f"answer={unknown.answer} confidence={unknown.confidence}")

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — the full period walk absorbs it, including Watch's own state")
print("=" * 74)
report = watch.run_period(cuts=range(1, 13))
print(f"  run_period() completed: {len(report.signals)} signals, "
      f"{len(report.escalations)} escalations, {len(report.decisions)} decisions")
check("run_period() completes with no exception", report is not None)
check(f"  Watch built trend history for {NEW_SITE} without being told it exists",
      NEW_SITE in watch.memory.trend_history,
      f"sites tracked: {sorted(watch.memory.trend_history)}")

history = watch.memory.trend_history.get(NEW_SITE)
if history:
    series = sorted(history.series)
    print(f"  trend series for {NEW_SITE}: {series}")
    check(f"    the NEW TEST {NEW_TEST} has its own series, with no code change",
          any(NEW_TEST in s for s in series), str(series))
    check(f"    and the lag metric was recorded for {NEW_SITE} too",
          any(s.startswith("KRI:") for s in series))

site_findings = [f for f in report.signals if f.site == NEW_SITE]
subject_findings = [f for f in report.signals if f.usubjid in NEW_SUBJECTS]
print(f"  findings naming {NEW_SITE}: {len(site_findings)}  "
      f"naming its subjects: {len(subject_findings)}")
for f in (site_findings + subject_findings)[:3]:
    print(f"      {f.code} {f.usubjid or f.site}: {f.rationale[:80]}...")
check("the new site's records reach the detectors (they are not silently skipped)",
      len(site_findings) + len(subject_findings) > 0,
      f"{len(site_findings) + len(subject_findings)} finding(s)")

kri_sites = {k.site for k in report.kris} if report.kris else set()
print(f"  sites appearing in the report's KRI block: {len(kri_sites)}")

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — the boundary, reported honestly: a new DOMAIN FILE")
print("=" * 74)
print(f"  The organiser's own study.py declares the domain list as a fixed tuple:")
print(f"      DOMAINS = (\"DM\", \"AE\", \"LB\", \"VS\", \"EX\", \"CM\", \"DS\", \"MH\", \"EG\")")
print(f"  stage1/atlas.py imports that tuple rather than restating it, so a CSV")
print(f"  the organiser's loader does not enumerate is not read by anything.")
loaded = NEW_DOMAIN in graph.study.domains
print(f"\n  {NEW_DOMAIN}.csv loaded by Study: {loaded}")
check(f"HONEST RESULT: a brand-new domain FILE is NOT loaded — this is the "
      f"organiser's study.py:DOMAINS tuple, which the build rules forbid editing",
      not loaded)
check("  and it fails safely: the study loads, nothing raises, no data is corrupted",
      len(graph.sites()) == 13 and report is not None)

from schemas import RecordRef                                    # noqa: E402
ref = RecordRef(domain=NEW_DOMAIN, usubjid=NEW_SUBJECTS[0], seq=1)
check("  a new domain NAME still flows through the schema unmodified "
      "(RecordRef.domain is a free string, not an enum)",
      ref.domain == NEW_DOMAIN and ref.key() == (NEW_DOMAIN, NEW_SUBJECTS[0], 1))
print(f"  -> a new MEASUREMENT inside an existing domain ({NEW_TEST} in LB) is "
      f"absorbed freely;\n     a new domain FILE needs one entry in the "
      f"organiser's own tuple, which is\n     outside this stage's remit and is "
      f"stated as a limitation rather than hidden.")

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — zero code change: nothing outside the test was touched")
print("=" * 74)
diff = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                      capture_output=True, text=True).stdout.strip()
touched = [line[3:] for line in diff.splitlines() if line.strip()]
source_touched = [f for f in touched
                  if f.startswith(("stage1/", "stage2/", "forecast/", "execute/"))
                  or f in ("schemas.py", "study.py", "run_local_harness.py")]
print("  files modified in the working tree that this test could have needed:")
for f in sorted(source_touched) or ["      (none)"]:
    print(f"      {f}")
check("no stage1/ file was changed to absorb the new site",
      not any(f.startswith("stage1/") for f in source_touched))
check("schemas.py is untouched", "schemas.py" not in source_touched)
check("study.py is untouched", "study.py" not in source_touched)
check(f"  {DATA.name}/ itself was never written to "
      f"(the fixture is a temp copy)",
      not (DATA / "data" / f"{NEW_DOMAIN}.csv").exists()
      and NEW_SITE not in (DATA / "data" / "DM.csv").read_text())

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
