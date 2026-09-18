"""SarvamKeyPool — round-robin across Sarvam accounts, with failover.

Backend-only (Act 1). Never imported by stage1/atlas.py — see TRD §2.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field


class NoSarvamKeysConfigured(Exception):
    """No usable Sarvam key was found in the environment."""


def _load_keys() -> list[str]:
    """Read Sarvam keys from the environment, tolerant of naming variants.

    Canonical form is `SARVAM_API_KEYS=key1,key2,key3` (comma-separated, one
    per pooled account), per build-instructions §B.1. Also accepted, so a
    hand-edited .env with a single key under a slightly different name still
    works without editing:
      - any case of SARVAM_API_KEYS
      - SARVAM_API_KEY (singular) as a one-key pool
    A one-key pool still functions correctly — it simply has no partner to
    fail over to, which is reported plainly in the pool's state rather than
    silently pretending otherwise.
    """
    for name in ("SARVAM_API_KEYS", "sarvam_api_keys", "Sarvam_Api_Keys"):
        raw = os.environ.get(name)
        if raw:
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            if keys:
                return keys
    for name in ("SARVAM_API_KEY", "sarvam_api_key", "Sarvam_Api_Key"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return [raw.strip()]
    return []


@dataclass
class _KeyState:
    key: str
    cooldown_until: float = 0.0


class SarvamKeyPool:
    """Round-robins across configured Sarvam API keys with cooldown-based failover.

    `.next_key()` returns the next key in rotation that isn't currently in
    cooldown. `.mark_exhausted(key)` puts a key in cooldown (default 60s) after
    a 429 or an "insufficient credit"-shaped response, so a temporarily
    rate-limited account recovers on its own rather than being permanently
    dropped. If every key is in cooldown, the least-recently-cooled one is
    returned anyway (a stale key is still a better bet than none), so a caller
    always gets *something* to try — thread-safe via a plain lock, since the
    FastAPI backend may serve concurrent avatar turns.
    """

    def __init__(self, keys: list[str] | None = None, cooldown_seconds: float = 60.0):
        loaded = keys if keys is not None else _load_keys()
        if not loaded:
            raise NoSarvamKeysConfigured(
                "no Sarvam key found — set SARVAM_API_KEYS (comma-separated) "
                "or SARVAM_API_KEY in .env")
        self._states = [_KeyState(k) for k in loaded]
        self._cooldown = cooldown_seconds
        self._i = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._states)

    @property
    def pool_size(self) -> int:
        return len(self._states)

    def next_key(self) -> str:
        """The next available key in rotation."""
        with self._lock:
            now = time.monotonic()
            n = len(self._states)
            for offset in range(n):
                idx = (self._i + offset) % n
                st = self._states[idx]
                if st.cooldown_until <= now:
                    self._i = (idx + 1) % n
                    return st.key
            # everyone's cooling down — hand back the one closest to ready
            st = min(self._states, key=lambda s: s.cooldown_until)
            self._i = (self._states.index(st) + 1) % n
            return st.key

    def mark_exhausted(self, key: str) -> None:
        """Put a key in cooldown after a 429 / insufficient-credit response."""
        with self._lock:
            for st in self._states:
                if st.key == key:
                    st.cooldown_until = time.monotonic() + self._cooldown
                    return

    def call_with_failover(self, fn, *, attempts: int | None = None):
        """Call fn(key) -> result, retrying with the next key on a pool-shaped error.

        `fn` should raise `SarvamRateLimited` (see sarvam_client.py) on a 429 or
        insufficient-credit response; any other exception propagates immediately
        — failover is only for account-exhaustion errors, not for e.g. a
        malformed request, which a different key would fail identically.
        """
        attempts = attempts or len(self._states)
        last_exc: Exception | None = None
        for _ in range(max(1, attempts)):
            key = self.next_key()
            try:
                return fn(key)
            except SarvamRateLimited as exc:
                self.mark_exhausted(key)
                last_exc = exc
                continue
        raise last_exc or NoSarvamKeysConfigured("no keys available")


class SarvamRateLimited(Exception):
    """Raised by a caller of `call_with_failover` on a 429 / insufficient-credit response."""
