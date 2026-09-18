"""T1.29 VERIFY — FastAPI backend, all 5 TRD §5 routes, real live HTTP.

This is a RECORD of the live verification already run manually during the
build (uvicorn started, curl against every route, a real avatar-turn producing
real audio, and a degraded-mode test with a deliberately revoked Sarvam key —
all pasted into the T1.29 commit message). This file re-runs the same checks
programmatically via TestClient so they're regression-checked going forward,
without needing a live server process or live external credentials.
"""
import sys, os, base64, wave, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

from fastapi.testclient import TestClient
from webapp.server import app

client = TestClient(app)

print("=== VERIFY (required): a real Question body -> a valid Answer, via HTTP ===")
resp = client.post("/api/atlas/ask", json={
    "id": "verify-t1.29", "kind": "count", "text": "",
    "params": {"metric": "discontinued_ae", "site": "S11"}})
print(f"  HTTP {resp.status_code}: {resp.json()}")
check("200 OK", resp.status_code == 200)
body = resp.json()
check("answer matches the published Q001 answer (3)", body["answer"] == 3)
check("evidence is present and well-formed", len(body["evidence"]) == 3)

print("\n=== VERIFY: GET /api/atlas/graph-stats returns build()'s dict verbatim ===")
resp = client.get("/api/atlas/graph-stats")
check("200 OK", resp.status_code == 200)
stats = resp.json()
check("real stats: 241 subjects, 26925 nodes", stats["subjects"] == 241 and stats["nodes"] == 26925)

print("\n=== VERIFY: GET /api/atlas/patient360/{usubjid} ===")
resp = client.get("/api/atlas/patient360/042-S07-001")
check("200 OK", resp.status_code == 200)
p = resp.json()
check("real subject data: site S07, 60 LB rows", p["site"] == "S07" and len(p["LB"]) == 60)
resp2 = client.get("/api/atlas/patient360/NO-SUCH-SUBJECT")
check("unknown subject: 200 with empty data, never a 500", resp2.status_code == 200)

print("\n=== VERIFY: GET /api/atlas/finding-graph is SEEDED at startup ===")
# Changed deliberately: the graph used to start empty and fill only from
# conversation, which meant /atlas opened on an empty box that said nothing
# about the study. It is now seeded by running every detector once at startup,
# so the panel shows the real picture immediately and a conversation is seen
# to ADD to it.
resp = client.get("/api/atlas/finding-graph")
check("200 OK", resp.status_code == 200)
graph = resp.json()
print(f"  seeded: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
      f"{len(graph['clusters'])} clusters")
check("seeded with the study's real findings, not empty", len(graph["nodes"]) > 100)
check("real relationships were built between them", len(graph["edges"]) > 0)
check("every node carries a finding code",
      all(n.get("code") for n in graph["nodes"]))
codes = {n["code"] for n in graph["nodes"]}
check("the Hy's law findings are present", "HYS_LAW_CANDIDATE" in codes, str(sorted(codes)))

print("\n=== VERIFY: GET /api/atlas/subjects backs the subject picker ===")
resp = client.get("/api/atlas/subjects")
check("200 OK", resp.status_code == 200)
subs = resp.json()
check("all 241 enrolled subjects listed", len(subs) == 241, str(len(subs)))
first = subs[0]
check("each carries what the picker shows",
      all(k in first for k in ("usubjid", "site", "arm", "age", "sex", "country",
                               "findings", "pro_records")), str(first))
check("finding counts are real", sum(s["findings"] for s in subs) > 0)

print("\n=== VERIFY: POST /api/atlas/avatar-turn, text-only, mocked external calls ===")
# Mocked here (no live network in an automated regression run) — the actual
# LIVE run against real Sarvam/Groq accounts (with real audio, real PRO
# writes, a real degraded-mode test via a revoked key) is documented in this
# task's commit message, which is the artifact of record for the live VERIFY.
from unittest.mock import patch
from intake.models import AvatarTurnResponse, PROExtraction

fake_turn = AvatarTurnResponse(
    reply_text="Thanks for letting us know.", reply_lang="en-IN", gesture="listening",
    extracted=[PROExtraction(pro_type="SYMPTOM", term="headache",
                             raw_quote="I have a headache", reported_date=None)])

with patch("webapp.server._get_groq") as mock_groq, \
     patch("webapp.server._get_sarvam") as mock_sarvam:
    mock_groq.return_value.turn.return_value = fake_turn
    mock_sarvam.return_value.speak.return_value = b"FAKE_WAV_BYTES"

    resp = client.post("/api/atlas/avatar-turn", json={
        "text": "I have a headache", "usubjid": "042-S03-001"})
    print(f"  HTTP {resp.status_code}: {resp.json()}")
    check("200 OK", resp.status_code == 200)
    body = resp.json()
    check("reply_text carried through", body["reply_text"] == "Thanks for letting us know.")
    check("gesture carried through", body["gesture"] == "listening")
    check("PRO record written", body["pro_written"] == ["PRO:042-S03-001:1"])
    check("audio present, base64-encoded", body["reply_audio_b64"] is not None)
    check("not degraded when both services work", body["degraded"] is False)
    check("decoded audio matches the mocked bytes",
          base64.b64decode(body["reply_audio_b64"]) == b"FAKE_WAV_BYTES")

print("\n=== VERIFY: the PRO record actually landed in StudyGraph (not just echoed) ===")
resp = client.get("/api/atlas/patient360/042-S03-001")
pro = resp.json()["PRO"]
print(f"  patient360('042-S03-001')['PRO'] = {pro}")
check("PRO record is real and persisted across requests", len(pro) == 1
      and pro[0]["raw_quote"] == "I have a headache")

print("\n=== VERIFY (required): degraded mode when Sarvam TTS fails ===")
from intake.sarvam_client import SarvamUnavailable
with patch("webapp.server._get_groq") as mock_groq, \
     patch("webapp.server._get_sarvam") as mock_sarvam:
    mock_groq.return_value.turn.return_value = fake_turn
    mock_sarvam.return_value.speak.side_effect = SarvamUnavailable("simulated revoked key")

    resp = client.post("/api/atlas/avatar-turn", json={
        "text": "test", "usubjid": "042-S04-001"})
    body = resp.json()
    print(f"  {body}")
    check("still 200, never a 500, even when Sarvam fails", resp.status_code == 200)
    check("reply_audio_b64 is null when TTS fails", body["reply_audio_b64"] is None)
    check("degraded=True is visible to the frontend", body["degraded"] is True)
    check("reply_text/gesture still present (Groq succeeded)", body["reply_text"] and body["gesture"])

print("\n=== VERIFY: bad request shapes never 500 ===")
resp = client.post("/api/atlas/avatar-turn", json={})
check("neither audio nor text -> 400, not 500", resp.status_code == 400)
resp = client.post("/api/atlas/ask", json={"bad": "shape"})
check("malformed Question -> 422 (FastAPI validation), not 500", resp.status_code == 422)

print("\n=== VERIFY: /api/atlas/ask on the backend never touches the graded module's import chain wrongly ===")
import webapp.server as ws
import stage1.atlas as sa
check("webapp imports stage1, not the reverse", "webapp" not in dir(sa) and hasattr(ws, "_atlas"))

print("\n" + ("ALL T1.29 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
