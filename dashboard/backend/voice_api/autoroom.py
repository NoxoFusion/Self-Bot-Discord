"""Dashboard API for Auto-Room mode.

The GET handler reads the ``auto_room`` section the Voice cog writes into
``voice_state.json``. The PUT handler validates the config and queues an
``auto_room`` command for the running bot; it never touches Discord directly.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..app import (
    VOICE_STATE_PATH_KEY,
    _is_digits,
    _is_int,
    _read_json,
    _validation_error,
    _voice_queue_or_error,
)
from ..voice import read_voice_state

PROTECTED_PATHS = {"/api/v1/voice/auto-room"}
PROTECTED_MUTATION_PATHS = {"/api/v1/voice/auto-room"}

AUTO_ROOM_PATH = "/api/v1/voice/auto-room"
SNOWFLAKE_MIN_LENGTH = 17
SNOWFLAKE_MAX_LENGTH = 20
MIN_LEADERS = 1
MAX_LEADERS = 5
MAX_MANUAL_ROOMS = 50

DEFAULT_AUTO_ROOM = {
    "enabled": False,
    "guild_id": None,
    "lobby_channel_id": None,
    "leader_count": 1,
    "manual": [],
}


def _is_snowflake(value: Any) -> bool:
    """Return ``True`` for a 17-20 digit Discord snowflake string."""

    return (
        _is_digits(value)
        and SNOWFLAKE_MIN_LENGTH <= len(value) <= SNOWFLAKE_MAX_LENGTH
    )


def _manual_from_state(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the normalized list of manually managed room tokens."""

    raw = config.get("manual")
    if not isinstance(raw, list):
        return []

    manual: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue

        index = entry.get("index")
        guild_id = entry.get("guild_id")
        channel_id = entry.get("channel_id")
        if not _is_int(index) or index < 0:
            continue
        if not _is_snowflake(guild_id) or not _is_snowflake(channel_id):
            continue

        manual.append(
            {
                "index": index,
                "guild_id": guild_id,
                "channel_id": channel_id,
            }
        )
        if len(manual) >= MAX_MANUAL_ROOMS:
            break

    return manual


def _auto_room_from_state(state: Any) -> dict[str, Any]:
    """Return a normalized ``auto_room`` section from the bot's state file."""

    config = state.get("auto_room") if isinstance(state, dict) else None
    if not isinstance(config, dict):
        return {**DEFAULT_AUTO_ROOM, "manual": []}

    guild_id = config.get("guild_id")
    lobby_channel_id = config.get("lobby_channel_id")
    leader_count = config.get("leader_count")

    return {
        "enabled": config.get("enabled") is True,
        "guild_id": guild_id if _is_snowflake(guild_id) else None,
        "lobby_channel_id": (
            lobby_channel_id if _is_snowflake(lobby_channel_id) else None
        ),
        "leader_count": (
            leader_count
            if _is_int(leader_count)
            and MIN_LEADERS <= leader_count <= MAX_LEADERS
            else 1
        ),
        "manual": _manual_from_state(config),
    }


async def get_auto_room(request: web.Request) -> web.Response:
    state = read_voice_state(request.app[VOICE_STATE_PATH_KEY])
    payload = _auto_room_from_state(state)
    payload["updated_at"] = state.get("updated_at")
    return web.json_response(payload)


async def put_auto_room(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    enabled = body.get("enabled")
    guild_id = body.get("guild_id")
    lobby_channel_id = body.get("lobby_channel_id")
    leader_count = body.get("leader_count")

    errors: list[str] = []
    if not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")
    if not _is_snowflake(guild_id):
        errors.append("guild_id must be a 17-20 digit string")
    if not _is_snowflake(lobby_channel_id):
        errors.append("lobby_channel_id must be a 17-20 digit string")
    if (
        not _is_int(leader_count)
        or not MIN_LEADERS <= leader_count <= MAX_LEADERS
    ):
        errors.append("leader_count must be an integer between 1 and 5")

    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {
            "action": "auto_room",
            "enabled": enabled,
            "guild_id": guild_id,
            "lobby_channel_id": lobby_channel_id,
            "leader_count": leader_count,
        }
    )
    return web.json_response({"queued": True})


def register(app) -> None:
    """Attach the auto-room routes to the dashboard application."""

    app.router.add_get(AUTO_ROOM_PATH, get_auto_room)
    app.router.add_put(AUTO_ROOM_PATH, put_auto_room)
