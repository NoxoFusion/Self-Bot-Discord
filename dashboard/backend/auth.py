"""Pairing-code authentication, in-memory sessions, and CSRF checks."""

from __future__ import annotations

import secrets
import time
from collections import deque
from typing import Any

SESSION_COOKIE = "sb_dashboard_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
PAIRING_WINDOW_SECONDS = 60
PAIRING_MAX_ATTEMPTS = 5


def generate_pairing_code() -> str:
    """Return a fresh six-digit pairing code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def csrf_matches(session: dict[str, Any], supplied: str | None) -> bool:
    """Constant-time comparison of a request CSRF header with a session."""
    if not supplied:
        return False
    expected = session.get("csrf")
    if not isinstance(expected, str) or not expected:
        return False
    # compare_digest rejects non-ASCII str values; headers can contain them.
    try:
        supplied_bytes = supplied.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(supplied_bytes, expected.encode("utf-8"))


class AuthManager:
    """In-memory pairing sessions and per-IP pairing rate limiting."""

    def __init__(
        self,
        pairing_code: str,
        *,
        session_ttl: int = SESSION_TTL_SECONDS,
        pairing_window: int = PAIRING_WINDOW_SECONDS,
        pairing_max_attempts: int = PAIRING_MAX_ATTEMPTS,
    ):
        self.pairing_code = str(pairing_code)
        self.session_ttl = session_ttl
        self.pairing_window = pairing_window
        self.pairing_max_attempts = pairing_max_attempts
        self._sessions: dict[str, dict[str, Any]] = {}
        self._pair_attempts: dict[str, deque[float]] = {}

    def allow_pair_attempt(self, remote_ip: str) -> bool:
        """Record an attempt and return whether it is within the limit."""
        now = time.monotonic()
        attempts = self._pair_attempts.setdefault(remote_ip, deque())
        while attempts and now - attempts[0] >= self.pairing_window:
            attempts.popleft()
        if len(attempts) >= self.pairing_max_attempts:
            return False
        attempts.append(now)
        return True

    def verify_pairing_code(self, code: Any) -> bool:
        if not isinstance(code, str):
            return False
        try:
            supplied = code.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return secrets.compare_digest(
            supplied,
            self.pairing_code.encode("utf-8"),
        )

    def create_session(self) -> tuple[str, str]:
        """Create a session and return ``(session_token, csrf_token)``.

        The pairing code is rotated after a successful pairing so a code that
        leaked (for example into a startup log) cannot be reused.
        """
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[token] = {
            "csrf": csrf,
            "created_at": now,
            "last_seen": now,
        }
        self.pairing_code = generate_pairing_code()
        self._purge_expired(now)
        return token, csrf

    def get_session(self, token: str | None) -> dict[str, Any] | None:
        """Return a live session, refreshing ``last_seen``, or ``None``."""
        if not token:
            return None

        session = self._sessions.get(token)
        if session is None:
            return None

        now = time.time()
        if now - session["created_at"] >= self.session_ttl:
            self._sessions.pop(token, None)
            return None

        session["last_seen"] = now
        self._purge_expired(now)
        return session

    def delete_session(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def _purge_expired(self, now: float) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if now - session["created_at"] >= self.session_ttl
        ]
        for token in expired:
            self._sessions.pop(token, None)
