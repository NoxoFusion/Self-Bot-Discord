"""Bot adapter boundary for the dashboard.

The HTTP layer talks to the bot only through :class:`BotAdapter`.  This first
slice ships :class:`OfflineBotAdapter`: settings can be saved locally, but no
Discord action is applied.  A future official-bot adapter can implement the
same interface without changing the API handlers.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BotAdapter(ABC):
    """Extension point for a live Discord bot adapter."""

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return a secret-free bot status snapshot."""

    @abstractmethod
    def apply_automation(self, data: dict[str, Any]) -> tuple[bool, str]:
        """Apply automation settings and return ``(applied, reason)``."""

    @abstractmethod
    def apply_afk(self, data: dict[str, Any]) -> tuple[bool, str]:
        """Apply AFK settings and return ``(applied, reason)``."""

    @abstractmethod
    def apply_reactions(self, data: dict[str, Any]) -> tuple[bool, str]:
        """Apply reaction settings and return ``(applied, reason)``."""

    def run_utility(
        self, action: str, data: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        """Run a Utility action and return ``(applied, reason, result)``."""
        return False, "bot_offline", {}

    def can_queue(self) -> bool:
        """Whether a running bot will consume queued commands."""
        return True


class OfflineBotAdapter(BotAdapter):
    """Adapter used when no live bot connection exists.

    It deliberately reports every mutation as not applied so the dashboard can
    never claim a Discord action happened when it did not.
    """

    def get_status(self) -> dict[str, Any]:
        return {
            "state": "offline",
            "username": None,
            "user_id": None,
            "avatar_url": None,
            "latency_ms": None,
            "uptime_seconds": 0,
            "guild_count": 0,
            "last_reload": None,
        }

    def apply_automation(self, data: dict[str, Any]) -> tuple[bool, str]:
        return False, "bot_offline"

    def apply_afk(self, data: dict[str, Any]) -> tuple[bool, str]:
        return False, "bot_offline"

    def apply_reactions(self, data: dict[str, Any]) -> tuple[bool, str]:
        return False, "bot_offline"


class LiveBotAdapter(BotAdapter):
    """Adapter backed by the bot's status file and the shared state store.

    The bot writes ``bot_status.json`` every few seconds.  When that file is
    fresh the dashboard reports the bot online and accepts mutations (the bot
    polls ``runtime_state.json`` and applies them).  A stale or missing file
    means the bot process is not running.
    """

    def __init__(
        self,
        status_path: Path,
        stale_after: float = 30.0,
        voice_stale_after: float = 15.0,
    ) -> None:
        self._status_path = Path(status_path)
        self._stale_after = stale_after
        self._voice_stale_after = voice_stale_after

    def _read_status(
        self, stale_after: float | None = None
    ) -> dict[str, Any] | None:
        threshold = self._stale_after if stale_after is None else stale_after
        try:
            raw = json.loads(self._status_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            updated_at = float(raw.get("updated_at") or 0)
        except (TypeError, ValueError):
            return None
        if time.time() - updated_at > threshold:
            return None
        return raw

    def get_status(self) -> dict[str, Any]:
        status = self._read_status()
        if status is None:
            return OfflineBotAdapter().get_status()
        return {
            "state": "online",
            "username": status.get("username"),
            "user_id": status.get("user_id"),
            "avatar_url": status.get("avatar_url"),
            "latency_ms": status.get("latency_ms"),
            "uptime_seconds": status.get("uptime_seconds", 0),
            "guild_count": status.get("guild_count", 0),
            "last_state_sync": status.get("last_state_sync"),
            "sync_errors": status.get("sync_errors", 0),
            "last_error": status.get("last_error"),
            "last_reload": status.get("last_reload"),
        }

    def _online(self) -> bool:
        return self._read_status() is not None

    def can_queue(self) -> bool:
        return self._read_status(self._voice_stale_after) is not None

    def apply_automation(self, data: dict[str, Any]) -> tuple[bool, str]:
        return (True, "queued") if self._online() else (False, "bot_offline")

    def apply_afk(self, data: dict[str, Any]) -> tuple[bool, str]:
        return (True, "queued") if self._online() else (False, "bot_offline")

    def apply_reactions(self, data: dict[str, Any]) -> tuple[bool, str]:
        return (True, "queued") if self._online() else (False, "bot_offline")

    def run_utility(
        self, action: str, data: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        return False, "bot_offline", {}
