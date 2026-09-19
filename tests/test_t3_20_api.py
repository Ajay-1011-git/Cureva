"""T3.20 VERIFY — the four /api/watch/* routes, per cureva-stage3-trd.md §5.

Driven through FastAPI's own TestClient rather than a live port, so the test is
deterministic and needs no free socket. The same routes were also exercised
against a real `uvicorn` process with `curl` during the build; the behaviour
asserted here is what that produced.

The route that matters most is `explain`: an unrecognised id must come back
**200 with a real Explanation saying so**, never a bare 404. A 404 is
indistinguishable from a routing mistake, and "this decision is not in the
trace" is a genuine answer this system can give, not an error.

Run: .venv/bin/python tests/test_t3_20_api.py
"""
import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from schemas import Explanation, SurveillanceReport
from webapp.server import app

logging.basicConfig(level=logging.CRITICAL)

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")


client = TestClient(app)

# ==========================================================================
print("=" * 74)
print("PART 1 — POST /api/watch/run-period")
print("=" * 74)
response = client.post("/api/watch/run-period", json={"cuts": [1, 2, 3, 4]})
check("returns HTTP 200", response.status_code == 200, str(response.status_code))
body = response.json()
report = body["report"]
print(f"  duration_ms : {body['duration_ms']}")
print(f"  cuts        : {body['cuts']}")
print(f"  report      : decisions={len(report['decisions'])} "
      f"escalations={len(report['escalations'])} kris={len(report['kris'])} "
      f"signals={len(report['signals'])} markdown={len(report['markdown'])} chars")
for row in body["per_cut"]:
    print(f"      cut {row['cut']:>2} (v{row['protocol_version']}): "
          f"{row['findings']} findings, {row['deviations']} deviations, "
          f"{row['queries']} queries")

check("the body carries a real SurveillanceReport",
      SurveillanceReport.model_validate(report) is not None)
check("  every required field is populated",
      all(report[f] for f in SurveillanceReport.model_fields))
check("  per_cut gives the page the shape the organiser's type has no room for",
      len(body["per_cut"]) == 4
      and all("findings" in r for r in body["per_cut"]))
check("  the graded configuration is what ran: zero tokens spent",
      report["budget"]["tokens"]["spent"] == 0)

default = client.post("/api/watch/run-period", json={})
check("an empty body defaults to the full 1..12 period",
      default.status_code == 200
      and default.json()["cuts"] == list(range(1, 13)),
      str(default.json().get("cuts")))
full = default.json()["report"]
print(f"  full period : decisions={len(full['decisions'])} "
      f"escalations={len(full['escalations'])} kris={len(full['kris'])}")
check("  and produces a complete report", all(full[f] for f in
                                              SurveillanceReport.model_fields))

decision_id = full["decisions"][0]["id"]

# ==========================================================================
print()
print("=" * 74)
print("PART 2 — GET /api/watch/explain/{decision_id}")
print("=" * 74)
response = client.get(f"/api/watch/explain/{decision_id}")
check("a real decision returns HTTP 200", response.status_code == 200)
body = response.json()
explanation = body["explanation"]
print(f"  found       : {body['found']}")
print(f"  trace_files : {body['trace_files']}")
print(f"  what        : {explanation['what'][:120]}")
print(f"  lines       : {len(explanation['evidence_lines'])}")
print(f"  consistent  : {explanation['consistent_with_trace']}")
check("  it is a real Explanation",
      Explanation.model_validate(explanation) is not None)
check("  with real trace lines", len(explanation["evidence_lines"]) > 0)
check("  and it names the trace file it read", body["trace_files"])

print("\n  an UNRECOGNISED id:")
for bogus in ("ESC-not-real", "garbage", "ESC-0000000000000"):
    response = client.get(f"/api/watch/explain/{bogus}")
    body = response.json()
    check(f"  {bogus!r} returns 200, NOT 404",
          response.status_code == 200, str(response.status_code))
    check(f"    found is False", body["found"] is False)
    check(f"    it still returns a valid Explanation",
          Explanation.model_validate(body["explanation"]) is not None)
    check(f"    saying plainly that nothing matches",
          "No decision with id" in body["explanation"]["what"])
    check(f"    with nothing partial offered",
          not body["explanation"]["evidence_lines"]
          and not body["explanation"]["evidence"])
print(f"      example: {client.get('/api/watch/explain/ESC-nope').json()['explanation']['what']}")

# ==========================================================================
print()
print("=" * 74)
print("PART 3 — GET /api/watch/forecast")
print("=" * 74)
body = client.get("/api/watch/forecast").json()
print(f"  count : {body['count']}  walked: {body['walked']}")
print(f"  note  : {body['note'][:110]}")
check("returns HTTP 200 with rows",
      client.get("/api/watch/forecast").status_code == 200 and body["count"] > 0)
rows = body["forecasts"]
if rows:
    row = rows[0]
    print(f"  top row: {row['site']} {row['code']} decision={row['decision']}")
    print(f"      {row['headline'][:120]}")
    print(f"      assumptions carried: {len(row['forecast']['assumptions'])}")
check("EVERY row carries the decision it informed (FR-18)",
      all(r.get("escalation_id") and r.get("decision") for r in rows))
check("  every row carries its full assumptions, not just a number",
      all(len(r["forecast"]["assumptions"]) >= 5 for r in rows))
check("  no row is a forecast with insufficient history dressed up as one",
      not any(r["forecast"]["insufficient_history"] for r in rows))
check("  the payload states what the numbers are and are not",
      "not predictions" in body["note"]
      and "no date or external consequence" in body["note"])
check("  rows are ordered by breach probability, highest first",
      [r["forecast"]["breach_probability"] for r in rows]
      == sorted((r["forecast"]["breach_probability"] for r in rows), reverse=True))

# ==========================================================================
print()
print("=" * 74)
print("PART 4 — GET /api/watch/artifacts")
print("=" * 74)
response = client.get("/api/watch/artifacts")
body = response.json()
print(f"  count     : {body['count']}  walked: {body['walked']}")
print(f"  by_source : {body['by_source']}")
print(f"  by_kind   : {body['by_kind']}")
check("returns HTTP 200 with rows",
      response.status_code == 200 and body["count"] > 0)
rows = body["artifacts"]
check("every artifact is tagged with a real source",
      all(r["source"] in ("template_only", "polished") for r in rows))
check("  the counts by source add up", sum(body["by_source"].values()) == body["count"])
check("  the counts by kind add up", sum(body["by_kind"].values()) == body["count"])
check("  every artifact carries its own cited evidence",
      all(r["evidence"] or r["kind"] == "IRB_MEMO" for r in rows))
check("  and the real drafted text, not a summary",
      all(len(r["text"]) > 200 for r in rows))
sample = rows[0]
print(f"\n  a real row — {sample['kind']} ({sample['code']}), "
      f"source={sample['source']}:")
for line in sample["text"].splitlines()[:6]:
    print(f"      {line[:120]}")

# ==========================================================================
print()
print("=" * 74)
print("PART 5 — the watch routes do not disturb the review page")
print("=" * 74)
from webapp.server import WATCH_STATE_DIR, SESSION_STATE_DIR      # noqa: E402
print(f"  review page state : {SESSION_STATE_DIR}")
print(f"  period walk state : {WATCH_STATE_DIR}")
check("the period walk keeps its own state directory",
      WATCH_STATE_DIR != SESSION_STATE_DIR)
from webapp.server import _get_watch, _get_crew                   # noqa: E402
watch, crew = _get_watch(), _get_crew()
check("  and its own crew, separate from the review page's",
      watch is not None and watch.crew is not crew)
check("  with the Tribunal OFF, so a 12-cut walk cannot spend the day's "
      "Groq allowance", watch.crew.tribunal_enabled is False)
check("  which is also the graded configuration",
      watch.tokens.spent == 0)
health = client.get("/api/health")
check("the existing /api/health still answers", health.status_code == 200,
      str(health.status_code))

# The watch's state lives INSIDE the session directory, so /api/monitor/reset
# deletes the trace explain() reads. Resetting only the crew would leave a
# StudyWatch serving a finished report whose every decision id then answered
# "no decision with that id appears in the trace" — true, and useless.
print("\n  /api/monitor/reset must drop the period walk too:")
walked = client.post("/api/watch/run-period", json={"cuts": [1, 2, 3]}).json()
did = walked["report"]["decisions"][0]["id"]
check("  before reset: the decision explains", 
      client.get(f"/api/watch/explain/{did}").json()["found"] is True)
reset = client.post("/api/monitor/reset").json()
print(f"      reset -> {reset}")
check("  the reset reports that BOTH were dropped",
      "period walk" in reset.get("reset", []), str(reset.get("reset")))
check("  after reset: nothing stale is served",
      client.get("/api/watch/artifacts").json()["count"] == 0
      and client.get(f"/api/watch/explain/{did}").json()["found"] is False)
again = client.post("/api/watch/run-period", json={"cuts": [1, 2, 3]}).json()
check("  and a fresh walk rebuilds cleanly, with the same derived ids",
      again["report"]["decisions"][0]["id"] == did
      and client.get(f"/api/watch/explain/{did}").json()["found"] is True)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails[:5]}")
sys.exit(1 if fails else 0)
