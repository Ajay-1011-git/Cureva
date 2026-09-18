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

    def transcribe(self, audio_bytes: bytes, filename: str = "turn.wav") -> tuple[str, str]:
        """Speech (any supported language) -> (english_transcript, detected_lang_code).

        Uses mode=translate so the transcript always comes back in English
        regardless of the spoken language — matching the multilingual-intake
        requirement (PRD NFR-5) without a separate translation step.
        """
        def call(key: str) -> tuple[str, str]:
            try:
                resp = requests.post(
                    STT_URL,
                    headers={"api-subscription-key": key},
                    files={"file": (filename, audio_bytes, "audio/wav")},
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

    def speak(self, text: str, lang: str = "en-IN", speaker: str = "shubh") -> bytes:
        """Text -> decoded WAV bytes. Truncates to TTS_MAX_CHARS rather than
        raising — a slightly-clipped reply keeps the demo alive; a raised
        exception over a length limit would not."""
        clipped = text[:TTS_MAX_CHARS]

        def call(key: str) -> bytes:
            try:
                resp = requests.post(
                    TTS_URL,
                    headers={"api-subscription-key": key, "Content-Type": "application/json"},
                    json={"text": clipped, "target_language_code": lang,
                          "model": "bulbul:v3", "speaker": speaker},
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
