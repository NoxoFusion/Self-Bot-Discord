"""Bridge between the dashboard backend state and the running bot.

The dashboard backend persists its settings in ``dashboard/backend/runtime_state.json``
(dashboard shape).  The bot polls that file and maps it into ``data/state.json``
(bot shape) plus the in-memory cog state, so dashboard changes apply live.

The bot also writes ``dashboard/backend/bot_status.json`` so the backend's
``LiveBotAdapter`` can report an honest online/offline status.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data_store import DEFAULTS, STATE_FILE, update_state
from src import client_identity

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1] / "dashboard" / "backend"
STATUS_PATH = BACKEND_DIR / "bot_status.json"
RUNTIME_STATE_PATH = BACKEND_DIR / "runtime_state.json"
RELOAD_FLAG_PATH = Path("data/reload.flag")

# Sync observability — read by build_status()/the dashboard health endpoint.
_last_state_sync: float | None = None
_sync_errors: int = 0
_last_error: str | None = None

# Reload observability — outcome of the last dashboard-triggered live reload.
_last_reload: dict | None = None


def record_sync_ok() -> None:
    """Record a successful dashboard state sync and reset the error counter."""

    global _last_state_sync, _sync_errors, _last_error
    _last_state_sync = time.time()
    _sync_errors = 0
    _last_error = None


def record_sync_error(exc: Exception) -> None:
    """Record a failed dashboard state sync."""

    global _sync_errors, _last_error
    _sync_errors += 1
    _last_error = str(exc)


def get_sync_state() -> dict[str, Any]:
    """Return the current sync health snapshot."""

    return {
        "last_state_sync": _last_state_sync,
        "sync_errors": _sync_errors,
        "last_error": _last_error,
    }


def consume_reload_request() -> bool:
    """Return True once when the dashboard requested a live reload.

    The flag file is deleted best-effort before returning so a single request
    triggers exactly one reload.  Never raises.
    """

    try:
        if not RELOAD_FLAG_PATH.exists():
            return False
    except Exception:
        return False
    try:
        RELOAD_FLAG_PATH.unlink()
    except Exception as exc:
        logger.warning("Could not delete reload flag: %s", exc)
    return True


def record_reload_result(ok: bool, detail: str) -> None:
    """Record the outcome of the last dashboard-triggered reload."""

    global _last_reload
    _last_reload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "ok": bool(ok),
        "detail": str(detail)[:200],
    }


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_path = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def build_status(bot) -> dict[str, Any]:
    """Build the status snapshot the dashboard adapter reads."""

    user = getattr(bot, "user", None)
    started = getattr(bot, "start_time", None)
    uptime = 0
    if isinstance(started, datetime):
        uptime = max(0, int((datetime.now() - started).total_seconds()))
    latency = getattr(bot, "latency", 0) or 0
    try:
        latency_value = float(latency)
    except (TypeError, ValueError):
        latency_value = 0.0
    # discord.py reports ``inf`` until the first heartbeat ACK; round(inf)
    # raises OverflowError and used to break the whole status write.
    latency_ms = (
        round(latency_value * 1000) if math.isfinite(latency_value) else None
    )
    return {
        "state": "online",
        "username": getattr(user, "name", None),
        "user_id": str(user.id) if user is not None else None,
        "avatar_url": (
            str(user.display_avatar.url)
            if user is not None
            and getattr(user, "display_avatar", None) is not None
            else None
        ),
        "latency_ms": latency_ms,
        "uptime_seconds": uptime,
        "guild_count": len(getattr(bot, "guilds", []) or []),
        "updated_at": time.time(),
        "last_state_sync": _last_state_sync,
        "sync_errors": _sync_errors,
        "last_error": _last_error,
        "last_reload": _last_reload,
        # Live client fingerprint so dashboard REST calls match the gateway.
        "client_user_agent": client_identity.client_properties().get(
            "browser_user_agent"
        ),
        "client_super_properties": client_identity.super_properties(),
    }


def write_status(bot) -> None:
    try:
        _atomic_write(STATUS_PATH, build_status(bot))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Could not write bot status: %s", exc)


def _channel_id(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    return int(text)


def find_cog(bot, *names: str):
    """Return the first loaded cog whose name matches ``names`` (case-insensitive).

    ``bot.get_cog()`` is case-sensitive, so a dashboard/cog name mismatch such as
    ``"AFK"`` vs the real ``"Afk"`` silently resolves to ``None``.  Scanning
    ``bot.cogs`` avoids that class of bug.
    """

    cogs = getattr(bot, "cogs", None) or {}
    if not isinstance(cogs, dict):
        try:
            cogs = dict(cogs)
        except (TypeError, ValueError):
            return None
    wanted = {str(name).lower() for name in names if name}
    if not wanted:
        return None
    for name, cog in cogs.items():
        if str(name).lower() in wanted:
            return cog
    return None


def map_automation(data: dict[str, Any]) -> dict[str, Any]:
    """Map the dashboard automation payload to the bot's ``auto`` shape."""

    enabled = bool(data.get("enabled"))
    broadcaster = data.get("broadcaster") or {}
    auto_responses: dict[str, str] = {}
    # Keep triggers even while disabled: the cog gates on ``ar_enabled`` so the
    # dashboard payload can be re-enabled without losing its configuration.
    for trigger in data.get("triggers") or []:
        if not isinstance(trigger, dict):
            continue
        keyword = str(trigger.get("keyword") or "").strip().lower()
        reply = trigger.get("reply")
        if keyword and isinstance(reply, str) and reply:
            auto_responses[keyword] = reply

    mode = broadcaster.get("mode")
    if mode == "count":
        # Legacy dashboard label — the cog implements this behaviour as "message".
        mode = "message"
    if mode not in ("time", "message"):
        mode = "time"
    try:
        value = int(broadcaster.get("value") or 60)
    except (TypeError, ValueError):
        value = 60

    return {
        "auto_responses": auto_responses,
        "ar_enabled": enabled,
        "auto_mess_config": {
            "active": bool(enabled and broadcaster.get("enabled")),
            "mode": mode,
            "value": value,
            "channel_id": _channel_id(broadcaster.get("channel_id")),
        },
        "message_pool": [
            item for item in (data.get("pool") or []) if isinstance(item, str)
        ],
    }


def map_afk(data: dict[str, Any], bot_user_id: str) -> dict[str, str]:
    """Map the dashboard AFK payload to ``{user_id: reason}``.

    The reason is kept even while disabled; ``afk_enabled`` gates the reply.
    """

    reason = str(data.get("reason") or "").strip()
    if not reason or not bot_user_id:
        return {}
    return {str(bot_user_id): reason}


def map_afk_config(data: dict[str, Any]) -> dict[str, Any]:
    """Map the dashboard AFK payload to the normalized reply config.

    Never depends on ``enabled`` — the reply behaviour follows the config
    flags themselves so a disabled AFK can still be pre-configured.
    """

    raw_cooldown = data.get("cooldown", 10)
    if isinstance(raw_cooldown, bool):
        raw_cooldown = 10
    try:
        cooldown = int(raw_cooldown)
    except (TypeError, ValueError):
        cooldown = 10
    cooldown = max(3, min(60, cooldown))

    reply_mentions = data.get("reply_mentions", True)
    reply_dms = data.get("reply_dms", True)
    return {
        "cooldown": cooldown,
        "reply_mentions": (
            reply_mentions if isinstance(reply_mentions, bool) else True
        ),
        "reply_dms": reply_dms if isinstance(reply_dms, bool) else True,
    }


def _reaction_cooldown(value: Any) -> int:
    """Normalize the reaction pacing cooldown (1-30 seconds, default 3)."""

    if isinstance(value, bool):
        return 3
    try:
        cooldown = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(30, cooldown))


def map_reactions(data: dict[str, Any]) -> dict[str, Any]:
    """Map the dashboard reactions payload to the bot's ``reactions`` shape.

    Configuration is kept even while disabled; ``enabled`` gates the listener.
    """

    cooldown = _reaction_cooldown(data.get("cooldown"))
    enabled = bool(data.get("enabled"))

    target = data.get("target")
    channel_id = _channel_id(data.get("channel_id"))
    if target == "everyone" and channel_id is None:
        # Defensive: "everyone × all channels" is the configuration that gets
        # accounts flagged. The backend rejects it; refuse it here as well so
        # a stale stored payload can never re-arm it.
        logger.warning(
            "Reactions: target 'everyone' without a channel — ignoring the payload"
        )
        return {
            "user_id": None,
            "emojis": None,
            "channel_id": None,
            "cooldown": cooldown,
            "enabled": False,
        }

    if target == "everyone":
        user_id: Any = "@everyone"
    else:
        raw_user = str(data.get("user_id") or "").strip()
        user_id = int(raw_user) if raw_user.isdigit() else None

    emojis = [
        str(emoji).strip()
        for emoji in (data.get("emojis") or [])
        if isinstance(emoji, str) and str(emoji).strip()
    ]
    return {
        "user_id": user_id,
        # Space-joined: cogs/reactions.py splits on whitespace/comma.
        "emojis": " ".join(emojis) or None,
        "channel_id": channel_id,
        "cooldown": cooldown,
        "enabled": enabled,
    }


def _apply_afk_entry(
    afk: dict[str, str], bot_user_id: str, reason: str | None
) -> None:
    """Set or clear only the bot's own AFK entry, preserving other users."""

    if not bot_user_id:
        return
    if reason:
        afk[bot_user_id] = reason
    else:
        afk.pop(bot_user_id, None)


async def apply_runtime_state(bot, state: dict[str, Any]) -> None:
    """Apply dashboard settings to data/state.json and the live cogs."""

    auto = map_automation(state.get("automation") or {})
    bot_user_id = str(bot.user.id) if getattr(bot, "user", None) else ""
    afk_state = state.get("afk")
    if not isinstance(afk_state, dict):
        afk_state = {}
    afk_map = map_afk(afk_state, bot_user_id)
    afk_config = map_afk_config(afk_state)
    afk_enabled = bool(afk_state.get("enabled"))
    reactions = map_reactions(state.get("reactions") or {})

    def mutate(current: dict[str, Any]) -> None:
        current["auto"] = auto
        current["reactions"] = reactions
        current["afk_config"] = afk_config
        current["afk_enabled"] = afk_enabled
        afk = current.get("afk")
        if not isinstance(afk, dict):
            afk = {}
            current["afk"] = afk
        _apply_afk_entry(afk, bot_user_id, afk_map.get(bot_user_id))

    await update_state(STATE_FILE, DEFAULTS, mutate)

    auto_cog = find_cog(bot, "AutoMess")
    if auto_cog is not None:
        auto_cog.data = auto
        task = getattr(auto_cog, "auto_mess_task", None)
        active = auto["auto_mess_config"]["active"]
        if active and (task is None or task.done()):
            auto_cog.auto_mess_task = bot.loop.create_task(
                auto_cog._auto_mess_loop()
            )
        elif not active and task is not None and not task.done():
            task.cancel()
            auto_cog.auto_mess_task = None

    afk_cog = find_cog(bot, "Afk")
    if afk_cog is not None:
        afk_cog.config = afk_config
        afk_cog.afk_enabled = afk_enabled
        afk_data = getattr(afk_cog, "afk_data", None)
        if not isinstance(afk_data, dict):
            afk_data = {}
            afk_cog.afk_data = afk_data
        _apply_afk_entry(afk_data, bot_user_id, afk_map.get(bot_user_id))

    reactions_cog = find_cog(bot, "Reactions")
    if reactions_cog is not None:
        reactions_cog._enabled = reactions["enabled"]
        reactions_cog._user_id = reactions["user_id"]
        reactions_cog.auto_react_emojis = reactions["emojis"]
        reactions_cog.auto_react_channel_id = reactions["channel_id"]
        reactions_cog.cooldown = reactions["cooldown"]
