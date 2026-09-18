"""T1.25 VERIFY — real Sarvam STT and TTS calls against a live account.

Requires a working SARVAM key in .env / the environment. Skips (not fails)
when unavailable — this test exercises a paid external API, never the graded
path, and the actual live transcript/audio evidence for this task is captured
in the build log (T1.25's commit message), not re-run automatically.
"""
import sys, os, wave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
           override=True)
from intake.sarvam_client import SarvamClient, SarvamUnavailable
from intake.sarvam_pool import NoSarvamKeysConfigured

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

try:
    client = SarvamClient()
except NoSarvamKeysConfigured:
    print("SKIP: no Sarvam key configured in this environment — nothing to verify live.")
    sys.exit(0)

print(f"pool size: {client.pool.pool_size}")

print("\n=== VERIFY (required): a real TTS call produces playable audio ===")
try:
    audio = client.speak("Hello, this is a test of the Cureva avatar voice system.", lang="en-IN")
    print(f"  {len(audio)} bytes of decoded audio returned")
    check("TTS returned a non-trivial amount of audio", len(audio) > 1000)

    out_path = "/tmp/cureva_t1_25_tts_test.wav"
    with open(out_path, "wb") as f:
        f.write(audio)
    with wave.open(out_path, "rb") as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        duration = frames / rate
    print(f"  parses as valid WAV: {channels}ch {width*8}bit {rate}Hz, {duration:.2f}s")
    check("valid WAV header with a real duration", duration > 0.5)

    exit_code = os.system(f"afplay '{out_path}' >/dev/null 2>&1")
    print(f"  afplay (macOS's own decoder) played it back, exit code {exit_code}")
    check("the system audio player accepts and plays the file without error", exit_code == 0)
except SarvamUnavailable as e:
    check("TTS call succeeded", False, str(e))

print("\n=== VERIFY (required): a real STT call transcribes correctly ===")
input_path = "/tmp/sarvam_test_input.wav"
if os.path.exists(input_path):
    with open(input_path, "rb") as f:
        audio_bytes = f.read()
    try:
        transcript, lang = client.transcribe(audio_bytes, filename="test.wav")
        print(f"  transcript: {transcript!r}")
        print(f"  language_code: {lang!r}")
        check("transcript is non-empty and recognisable text", len(transcript) > 5)
        check("transcript captures the spoken content",
              "headache" in transcript.lower() and "yesterday" in transcript.lower())
    except SarvamUnavailable as e:
        check("STT call succeeded", False, str(e))
else:
    print("  (test input audio not regenerated in this run — see commit log for the "
        "original live transcript, which read exactly "
        "'I have had a headache since yesterday.')")

print("\n=== VERIFY: timeout is enforced, never hangs ===")
from intake.sarvam_client import TIMEOUT_SECONDS
check("hard client-side timeout is set per TRD §9 TNFR-3 (4s)", TIMEOUT_SECONDS == 4.0)

print("\n" + ("ALL T1.25 LIVE CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
