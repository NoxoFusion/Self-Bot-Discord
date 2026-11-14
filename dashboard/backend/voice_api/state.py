"""Dashboard API for voice state controls (mute/deafen/move).

All commands are queued for the running bot process; the bot applies them
through gateway opcode 4. No REST calls are made from the dashboard.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..app import (
    VOICE_STATE_PATH_KEY,
    _is_digits,
    _is_int,
    _read_json,
    _token_index_error,
    _validation_error,
    _voice_queue_or_error,
)
from ..voice import read_voice_state

PROTECTED_PATHS = {
    "/api/v1/voice/state",
    "/api/v1/voice/move",
    "/api/v1/voice/channels",
}
PROTECTED_MUTATION_PATHS = {
    "/api/v1/voice/state",
    "/api/v1/voice/move",
}

TOKEN_INDEX_MAX_DIGITS = 10


def _normalize_channels(value: Any) -> list[dict[str, Any]] | None:
    """Return a channel list from a cache entry, or ``None`` when unusable."""

    if isinstance(value, dict):
        value = value.get("channels")
    if not isinstance(value, list):
        return None

    channels: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        channel_id = entry.get("id")
        if channel_id is None:
            continue
        channels.append(
            {
                "id": str(channel_id),
                "name": entry.get("name"),
                "position": entry.get("position", 0),
            }
        )
    return channels


def _lookup_channels(
    cache: Any, token_index: int, guild_id: str
) -> list[dict[str, Any]] | None:
    """Find ``guild_id`` in a cache that may be flat or nested per token."""

    if isinstance(cache, list):
        for entry in cache:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id") or entry.get("guild_id")
            if str(entry_id) != guild_id:
                continue
            return _normalize_channels(entry.get("channels", entry))
        return None
    if not isinstance(cache, dict):
        return None
    if guild_id in cache:
        return _normalize_channels(cache[guild_id])
    token_key = str(token_index)
    if token_key in cache:
        return _lookup_channels(cache[token_key], token_index, guild_id)
    return None


def _channels_for_state(
    state: Any, token_index: int, guild_id: str
) -> list[dict[str, Any]]:
    """Read the bot-written channel cache from the voice state snapshot."""

    if not isinstance(state, dict):
        return []

    for key in ("guild_channels", "guilds", "channels_by_guild"):
        channels = _lookup_channels(state.get(key), token_index, guild_id)
        if channels is not None:
            return channels

    tokens = state.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            if str(token.get("index")) != str(token_index):
                continue
            for key in ("guild_channels", "guilds", "channels_by_guild"):
                channels = _lookup_channels(token.get(key), token_index, guild_id)
                if channels is not None:
                    return channels
    return []


def _query_token_index(value: Any) -> int | None:
    if not _is_digits(value) or len(value) > TOKEN_INDEX_MAX_DIGITS:
        return None
    return int(value)


async def post_voice_state(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    guild_id = body.get("guild_id")
    token_index = body.get("token_index")
    all_tokens = body.get("all")
    mute = body.get("mute")
    deaf = body.get("deaf")

    errors: list[str] = []
    if not _is_digits(guild_id):
        errors.append("guild_id must be a string of digits")
    if mute is None and deaf is None:
        errors.append("at least one of mute or deaf is required")
    if mute is not None and not isinstance(mute, bool):
        errors.append("mute must be a boolean")
    if deaf is not None and not isinstance(deaf, bool):
        errors.append("deaf must be a boolean")

    has_token = token_index is not None
    has_all = all_tokens is not None
    if has_token == has_all:
        errors.append("exactly one of token_index or all is required")
    elif has_token and (not _is_int(token_index) or token_index < 0):
        errors.append("token_index must be a non-negative integer")
    elif has_all and all_tokens is not True:
        errors.append("all must be true when provided")

    if has_token and _is_int(token_index) and token_index >= 0:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)

    if errors:
        return _validation_error(errors)

    command: dict[str, Any] = {
        "action": "voice_state",
        "guild_id": guild_id,
    }
    if has_all:
        command["all"] = True
    else:
        command["token_index"] = token_index
    if mute is not None:
        command["mute"] = mute
    if deaf is not None:
        command["deaf"] = deaf

    queue.enqueue(command)
    return web.json_response({"queued": True})


async def post_voice_move(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    guild_id = body.get("guild_id")
    channel_id = body.get("channel_id")

    errors: list[str] = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    if not _is_digits(guild_id):
        errors.append("guild_id must be a string of digits")
    if not _is_digits(channel_id):
        errors.append("channel_id must be a string of digits")
    if _is_int(token_index) and token_index >= 0:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)
    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {
            "action": "move",
            "token_index": token_index,
            "guild_id": guild_id,
            "channel_id": channel_id,
        }
    )
    return web.json_response({"queued": True})


async def get_voice_channels(request: web.Request) -> web.Response:
    token_index = _query_token_index(request.query.get("token_index"))
    guild_id = (request.query.get("guild_id") or "").strip()

    errors: list[str] = []
    if token_index is None:
        errors.append("token_index must be a non-negative integer")
    if not _is_digits(guild_id):
        errors.append("guild_id must be a string of digits")
    if errors:
        return _validation_error(errors)

    state = read_voice_state(request.app[VOICE_STATE_PATH_KEY])
    return web.json_response(
        {
            "channels": _channels_for_state(state, token_index, guild_id),
            "updated_at": state.get("updated_at"),
        }
    )


def register(app) -> None:
    app.router.add_post("/api/v1/voice/state", post_voice_state)
    app.router.add_post("/api/v1/voice/move", post_voice_move)
    app.router.add_get("/api/v1/voice/channels", get_voice_channels)
