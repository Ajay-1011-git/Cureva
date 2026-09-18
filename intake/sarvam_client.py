"""Sarvam STT/TTS wrappers — Act 1 only, never imported by stage1/atlas.py.

Shapes below were verified live against docs.sarvam.ai on this build session
(anti-hallucination rule 2), NOT assumed from build-instructions §B.4 alone.
Two things differ from what §B.4 wrote, both confirmed by fetching the current
docs directly:

  1. STT endpoint. §B.4 named POST /speech-to-text-translate. The CURRENT,
     documented endpoint is the unified POST /speech-to-text, with a `mode`
     form field ("transcribe" default, "translate" for cross-language, plus
     "verbatim"/"translit"/"codemix"). The older *-translate path may still
     exist for backward compatibility but the unified endpoint is what the
     docs now describe first, so that's what this client calls.
  2. TTS response. §B.4 said "decode audios[0]". The docs' own example joins
     ALL of `audios` before decoding ("".join(d["audios"])) — TTS on a long
     reply can come back as multiple chunks, and audios[0] alone would silently
     truncate a longer reply. This client joins the full list.

Verified request/response shape, as of this session:

  STT  POST https://api.sarvam.ai/speech-to-text
       headers: api-subscription-key: <key>
       multipart/form-data: file (audio binary), model ("saaras:v3"),
         mode ("translate" — cross-language input, always to English text),
         language_code (BCP-47 or "unknown" to auto-detect)
       response JSON: {request_id, transcript, language_code,
         language_probability, timestamps, diarized_transcript}
       REST constraint: 30 seconds of audio per request (longer needs the
         batch API, out of scope for a turn-based avatar).

  TTS  POST https://api.sarvam.ai/text-to-speech
       headers: api-subscription-key: <key>, Content-Type: application/json
       body: {text, target_language_code, model: "bulbul:v3", speaker}
       response JSON: {request_id, audios: [<base64 chunk>, ...]}
       constraint: 2500 characters per request (REST).
"""
from __future__ import annotations

import base64
import os

import requests

from .sarvam_pool import SarvamKeyPool, SarvamRateLimited

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

#: Hard client-side timeout on both calls (TRD §9 TNFR-3) — the live defense
#: must never appear to hang waiting on an external API.
TIMEOUT_SECONDS = 4.0

#: TTS request limit, confirmed current on docs.sarvam.ai.
TTS_MAX_CHARS = 2500

#: The avatar's voice. Sarvam's docs list bulbul:v3's speakers but do not label
#: them by gender; these six were each called live and confirmed to return
#: valid audio. Cureva's avatar is presented as female, so the default is a
#: female voice — "shubh", bulbul's own default, is male and was the wrong
#: choice here. Override with SARVAM_TTS_SPEAKER to pick a different one.
FEMALE_SPEAKERS = ("priya", "ritu", "neha", "kavya", "shreya", "suhani")
DEFAULT_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "priya")


class SarvamUnavailable(Exception):
    """STT/TTS could not complete — timeout, exhausted pool, or a hard error.

    Never lets a raw HTTP/connection exception surface to the caller; the
    webapp layer catches this specifically and falls back per TRD §8.
    """


def _is_rate_limited(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code in (402, 403):
        # "insufficient credit"-shaped response — Sarvam doesn't document a
        # single fixed status for this, so the body is inspected too.
        try:
            body = response.text.lower()
        except Exception:
            body = ""
        return "credit" in body or "quota" in body or "insufficient" in body
    return False


class SarvamClient:
    """Thin wrapper: transcribe(audio) -> (transcript, lang); speak(text, lang) -> bytes."""

    def __init__(self, pool: SarvamKeyPool | None = None):
        self.pool = pool or SarvamKeyPool()

    def transcribe(self, audio_bytes: bytes, filename: str = "turn.wav",
                   content_type: str | None = None) -> tuple[str, str]:
        """Speech (any supported language) -> (english_transcript, detected_lang_code).

        Uses mode=translate so the transcript always comes back in English
        regardless of the spoken language — matching the multilingual-intake
        requirement (PRD NFR-5) without a separate translation step.

        `content_type` must reflect what the bytes actually are. A browser's
        MediaRecorder produces webm or mp4 depending on the engine, not wav,
        and Sarvam rejects the upload outright when the declared type does not
        match (it 400s with an explicit "Invalid file type" listing what it
        accepts). It is threaded through from the caller rather than assumed;
        the extension is kept in step with it for the same reason.
        """
        # MediaRecorder hands back types like "audio/webm;codecs=opus" — the
        # parameters are not part of the type Sarvam matches on.
        ctype = (content_type or "audio/wav").split(";")[0].strip()
        extension = {
            "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4",
            "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav",
            "audio/x-wav": "wav", "audio/wave": "wav",
        }.get(ctype, "wav")
        if "." in filename:
            filename = f"{filename.rsplit('.', 1)[0]}.{extension}"

        def call(key: str) -> tuple[str, str]:
            try:
                resp = requests.post(
                    STT_URL,
                    headers={"api-subscription-key": key},
                    files={"file": (filename, audio_bytes, ctype)},
                    data={"model": "saaras:v3", "mode": "translate",
                          "language_code": "unknown"},
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise SarvamUnavailable(f"STT request failed: {exc}") from exc

            if _is_rate_limited(resp):
                raise SarvamRateLimited(f"STT rate-limited: HTTP {resp.status_code}")
            if resp.status_code != 200:
                raise SarvamUnavailable(f"STT error: HTTP {resp.status_code}: {resp.text[:200]}")

            try:
                body = resp.json()
            except ValueError as exc:
                raise SarvamUnavailable(f"STT returned non-JSON: {exc}") from exc

            transcript = body.get("transcript") or ""
            lang = body.get("language_code") or "unknown"
            return transcript, lang

        try:
            return self.pool.call_with_failover(call)
        except SarvamRateLimited as exc:
            raise SarvamUnavailable(f"STT: pool exhausted: {exc}") from exc

    def speak(self, text: str, lang: str = "en-IN",
              speaker: str | None = None) -> bytes:
        """Text -> decoded WAV bytes. Truncates to TTS_MAX_CHARS rather than
        raising — a slightly-clipped reply keeps the demo alive; a raised
        exception over a length limit would not."""
        clipped = text[:TTS_MAX_CHARS]
        voice = speaker or DEFAULT_SPEAKER

        def call(key: str) -> bytes:
            try:
                resp = requests.post(
                    TTS_URL,
                    headers={"api-subscription-key": key, "Content-Type": "application/json"},
                    json={"text": clipped, "target_language_code": lang,
                          "model": "bulbul:v3", "speaker": voice},
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise SarvamUnavailable(f"TTS request failed: {exc}") from exc

            if _is_rate_limited(resp):
                raise SarvamRateLimited(f"TTS rate-limited: HTTP {resp.status_code}")
            if resp.status_code != 200:
                raise SarvamUnavailable(f"TTS error: HTTP {resp.status_code}: {resp.text[:200]}")

            try:
                body = resp.json()
            except ValueError as exc:
                raise SarvamUnavailable(f"TTS returned non-JSON: {exc}") from exc

            chunks = body.get("audios") or []
            if not chunks:
                raise SarvamUnavailable("TTS response carried no audio")
            # Join every chunk before decoding — see module docstring point 2.
            return base64.b64decode("".join(chunks))

        try:
            return self.pool.call_with_failover(call)
        except SarvamRateLimited as exc:
            raise SarvamUnavailable(f"TTS: pool exhausted: {exc}") from exc
