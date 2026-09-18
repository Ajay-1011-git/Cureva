"""T1.32 — the spoken-turn path: mime handling, transcript echo, empty audio.

Deterministic and mocked: no network, no credentials. These are contracts the
voice path has to hold regardless of what Sarvam or Groq say on the day.

Written after the /atlas page shipped mute: there was no microphone capture at
all, and the transcribe() call hard-coded "audio/wav" while a browser's
MediaRecorder actually produces webm or mp4. Sarvam rejects a mismatched
declared type outright (HTTP 400, "Invalid file type"), so a real spoken turn
from the browser could never have worked.
"""
import base64
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []
def check(label, cond, detail=""):
    if not cond:
        fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

from intake.sarvam_client import SarvamClient, DEFAULT_SPEAKER, FEMALE_SPEAKERS
from intake.sarvam_pool import SarvamKeyPool

pool = SarvamKeyPool(keys=["k1"])
client = SarvamClient(pool=pool)


def capture_post(status=200, payload=None):
    """A requests.post stand-in that records exactly what was sent."""
    seen = {}
    def fake_post(url, **kw):
        seen["url"] = url
        seen.update(kw)
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = payload or {}
        resp.text = ""
        return resp
    return fake_post, seen


print("=== the declared mime type follows the actual audio, not a guess ===")
CASES = [
    ("audio/webm;codecs=opus", "audio/webm", "webm"),   # Chrome
    ("audio/mp4",              "audio/mp4",  "mp4"),     # Safari
    ("audio/ogg",              "audio/ogg",  "ogg"),     # Firefox
    (None,                     "audio/wav",  "wav"),     # default
]
for given, expected_type, expected_ext in CASES:
    fake_post, seen = capture_post(200, {"transcript": "hi", "language_code": "en-IN"})
    with patch("intake.sarvam_client.requests.post", fake_post):
        client.transcribe(b"x" * 4096, filename="turn.wav", content_type=given)
    sent_name, _sent_bytes, sent_type = seen["files"]["file"]
    check(f"{str(given):26} -> Content-Type {expected_type}", sent_type == expected_type,
          f"got {sent_type}")
    check(f"{str(given):26} -> filename .{expected_ext}",
          sent_name.endswith(f".{expected_ext}"), f"got {sent_name}")

print("\n=== codec parameters are stripped (Sarvam matches on the bare type) ===")
fake_post, seen = capture_post(200, {"transcript": "hi"})
with patch("intake.sarvam_client.requests.post", fake_post):
    client.transcribe(b"x" * 4096, content_type="audio/webm;codecs=opus")
check("';codecs=opus' never reaches the wire", ";" not in seen["files"]["file"][2])

print("\n=== STT asks for translate mode, so any language comes back usable ===")
check("mode=translate is sent", seen["data"]["mode"] == "translate")
check("model is saaras:v3", seen["data"]["model"] == "saaras:v3")
check("language is auto-detected", seen["data"]["language_code"] == "unknown")

print("\n=== the avatar speaks with a female voice by default ===")
fake_post, seen = capture_post(200, {"audios": [base64.b64encode(b"RIFF").decode()]})
with patch("intake.sarvam_client.requests.post", fake_post):
    client.speak("hello")
sent_speaker = seen["json"]["speaker"]
print(f"  default speaker: {sent_speaker!r}")
check("default speaker is one of the confirmed female voices",
      sent_speaker in FEMALE_SPEAKERS, f"got {sent_speaker!r}")
check("it is NOT bulbul's male default 'shubh'", sent_speaker != "shubh")
check("DEFAULT_SPEAKER is what actually gets sent", sent_speaker == DEFAULT_SPEAKER)
check("model is bulbul:v3", seen["json"]["model"] == "bulbul:v3")

print("\n=== the speaker is overridable per call and by environment ===")
fake_post, seen = capture_post(200, {"audios": [base64.b64encode(b"RIFF").decode()]})
with patch("intake.sarvam_client.requests.post", fake_post):
    client.speak("hello", speaker="ritu")
check("an explicit speaker wins", seen["json"]["speaker"] == "ritu")

print("\n=== multi-chunk TTS is joined before decoding, never truncated ===")
whole = b"RIFFthis-is-the-whole-reply"
b64 = base64.b64encode(whole).decode()
half = len(b64) // 2
fake_post, seen = capture_post(200, {"audios": [b64[:half], b64[half:]]})
with patch("intake.sarvam_client.requests.post", fake_post):
    got = client.speak("a long reply")
check("both chunks joined and decoded (audios[0] alone would truncate)",
      got == whole, f"got {got!r}")

print("\n=== a spoken turn echoes back what was actually heard ===")
from webapp.server import app
from fastapi.testclient import TestClient
from intake.models import AvatarTurnResponse, PROExtraction

http = TestClient(app)
turn = AvatarTurnResponse(reply_text="Noted.", reply_lang="en-IN", gesture="listening",
                          extracted=[PROExtraction(pro_type="SYMPTOM", term="headache",
                                                   raw_quote="my head hurts",
                                                   reported_date=None)])
with patch("webapp.server._get_groq") as g, patch("webapp.server._get_sarvam") as sv:
    g.return_value.turn.return_value = turn
    sv.return_value.transcribe.return_value = ("my head hurts", "en-IN")
    sv.return_value.speak.return_value = b"WAV"
    r = http.post("/api/atlas/avatar-turn", json={
        "audio_b64": base64.b64encode(b"x" * 4096).decode(),
        "audio_mime": "audio/webm", "usubjid": "042-S01-001"})
body = r.json()
print(f"  {body}")
check("200 OK", r.status_code == 200)
check("transcript is returned so the page can show what was heard",
      body["transcript"] == "my head hurts")
check("the recorded mime type is forwarded to Sarvam",
      sv.return_value.transcribe.call_args.kwargs.get("content_type") == "audio/webm")
check("a PRO record was written from the spoken turn", body["pro_written"])

print("\n=== a typed turn carries no transcript (nothing was heard) ===")
with patch("webapp.server._get_groq") as g, patch("webapp.server._get_sarvam") as sv:
    g.return_value.turn.return_value = turn
    sv.return_value.speak.return_value = b"WAV"
    r = http.post("/api/atlas/avatar-turn",
                  json={"text": "my head hurts", "usubjid": "042-S01-001"})
check("transcript is null for a typed turn", r.json()["transcript"] is None)

print("\n=== silence is reported as such, not sent onward as an empty prompt ===")
with patch("webapp.server._get_groq") as g, patch("webapp.server._get_sarvam") as sv:
    sv.return_value.transcribe.return_value = ("   ", "en-IN")
    r = http.post("/api/atlas/avatar-turn", json={
        "audio_b64": base64.b64encode(b"x" * 4096).decode(), "audio_mime": "audio/webm"})
    body = r.json()
    print(f"  {body['reply_text']!r}")
    check("200, not an error", r.status_code == 200)
    check("says it didn't catch that", "didn't catch" in body["reply_text"])
    check("Groq is never called with an empty prompt", not g.return_value.turn.called)
    check("nothing is written from silence", body["pro_written"] == [])

print("\n" + ("ALL T1.32 VOICE-PATH CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
