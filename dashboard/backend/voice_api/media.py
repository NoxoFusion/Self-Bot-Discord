"""Dashboard API for audio playback control (queue/play/stop/skip).

Mutation handlers only validate and enqueue commands for the running bot; the
bot performs the actual voice playback. The queue endpoint reads the ``audio``
section the bot writes into ``voice_state.json``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

try:  # yt-dlp is optional in minimal installs
    import yt_dlp
except ImportError:  # pragma: no cover - depends on the runtime image
    yt_dlp = None  # type: ignore[assignment]

try:
    from src.audio_search import normalize_query, rank_entries
except Exception:  # pragma: no cover - optional module or missing sys.path
    normalize_query = None  # type: ignore[assignment]
    rank_entries = None  # type: ignore[assignment]

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
    "/api/v1/voice/play",
    "/api/v1/voice/search",
    "/api/v1/voice/audio/stop",
    "/api/v1/voice/audio/skip",
    "/api/v1/voice/audio/queue",
}
PROTECTED_MUTATION_PATHS = {
    "/api/v1/voice/play",
    "/api/v1/voice/search",
    "/api/v1/voice/audio/stop",
    "/api/v1/voice/audio/skip",
    "/api/v1/voice/audio/loop",
    "/api/v1/voice/audio/replay",
    "/api/v1/voice/audio/filters",
    "/api/v1/voice/audio/volume",
    "/api/v1/voice/audio/forcefix",
}

PLAY_PATH = "/api/v1/voice/play"
SEARCH_PATH = "/api/v1/voice/search"
STOP_PATH = "/api/v1/voice/audio/stop"
SKIP_PATH = "/api/v1/voice/audio/skip"
LOOP_PATH = "/api/v1/voice/audio/loop"
REPLAY_PATH = "/api/v1/voice/audio/replay"
QUEUE_PATH = "/api/v1/voice/audio/queue"
FILTERS_PATH = "/api/v1/voice/audio/filters"
VOLUME_PATH = "/api/v1/voice/audio/volume"
FORCEFIX_PATH = "/api/v1/voice/audio/forcefix"

SNOWFLAKE_MIN_LENGTH = 17
SNOWFLAKE_MAX_LENGTH = 20
TOKEN_INDEX_MAX_DIGITS = 10
QUERY_MAX_LENGTH = 300
SEARCH_RESULTS_LIMIT = 6
SEARCH_TIMEOUT_SECONDS = 20.0

AUDIO_FILTER_KEYS = frozenset(
    {
        "bass",
        "soft",
        "lofi",
        "slowed reverb",
        "reverb",
        "sped up",
        "dolby",
        "8d",
        "concert",
        "instrumental",
    }
)
AUDIO_FILTERS_MAX = 10
BASS_LEVEL_MIN = 1
BASS_LEVEL_MAX = 999
VOLUME_MIN = 0
VOLUME_MAX = 200
LOOP_MODES = frozenset({"off", "track", "queue"})


def _is_snowflake(value: Any) -> bool:
    """Return ``True`` for a 17-20 digit Discord snowflake string."""

    return (
        _is_digits(value)
        and SNOWFLAKE_MIN_LENGTH <= len(value) <= SNOWFLAKE_MAX_LENGTH
    )


def _audio_section(state: Any) -> dict[str, Any]:
    """Return the ``audio`` map from the bot's state snapshot, or ``{}``."""

    audio = state.get("audio") if isinstance(state, dict) else None
    return audio if isinstance(audio, dict) else {}


def _search_flat_entries(query: str) -> list[dict[str, Any]]:
    """Return raw yt-dlp flat search entries for ``query`` (blocking)."""

    options = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch10:{query}", download=False)

    entries = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _search_results(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map ranked flat entries to the compact dashboard result shape."""

    results: list[dict[str, Any]] = []
    for entry in entries:
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        url = entry.get("webpage_url")
        if not isinstance(url, str) or not url.strip():
            video_id = entry.get("id")
            url = (
                f"https://www.youtube.com/watch?v={video_id}"
                if isinstance(video_id, str) and video_id.strip()
                else None
            )
        if not url:
            continue

        uploader = entry.get("uploader") or entry.get("channel") or ""
        results.append(
            {
                "title": title.strip(),
                "uploader": uploader if isinstance(uploader, str) else "",
                "duration": entry.get("duration"),
                "url": url.strip(),
            }
        )
        if len(results) >= SEARCH_RESULTS_LIMIT:
            break
    return results


async def post_voice_search(request: web.Request) -> web.Response:
    """Search YouTube for the dashboard picker without starting playback."""

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    query = body.get("query")
    errors: list[str] = []
    if not isinstance(query, str) or not query.strip():
        errors.append("query must be a non-empty string")
    elif len(query.strip()) > QUERY_MAX_LENGTH:
        errors.append("query must be at most 300 characters")
    if errors:
        return _validation_error(errors)

    if yt_dlp is None or normalize_query is None or rank_entries is None:
        return web.json_response({"error": "search_unavailable"}, status=503)

    cleaned = query.strip()
    try:
        entries = await asyncio.wait_for(
            asyncio.to_thread(_search_flat_entries, cleaned),
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
        normalized, modifiers = normalize_query(cleaned)
        ranked = rank_entries(entries, normalized, modifiers)
        results = _search_results(ranked)
    except Exception:
        return web.json_response(
            {
                "error": "search_failed",
                "message": "Could not search YouTube. Try again.",
            },
            status=502,
        )

    return web.json_response({"results": results})


async def post_voice_play(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    guild_id = body.get("guild_id")
    channel_id = body.get("channel_id")
    query = body.get("query")

    errors: list[str] = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    else:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)
    if guild_id not in (None, "") and not _is_snowflake(guild_id):
        errors.append("guild_id must be a 17-20 digit string")
    if not _is_snowflake(channel_id):
        errors.append("channel_id must be a 17-20 digit string")
    if not isinstance(query, str) or not query.strip():
        errors.append("query must be a non-empty string")
    elif len(query.strip()) > QUERY_MAX_LENGTH:
        errors.append("query must be at most 300 characters")

    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {
            "action": "play",
            "token_index": token_index,
            "guild_id": guild_id or "",
            "channel_id": channel_id,
            "query": query.strip(),
        }
    )
    return web.json_response({"queued": True})


async def _post_audio_control(
    request: web.Request, action: str
) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    if not _is_int(token_index) or token_index < 0:
        return _validation_error(
            ["token_index must be a non-negative integer"]
        )
    token_error = _token_index_error(token_index)
    if token_error is not None:
        return _validation_error([token_error])

    queue.enqueue({"action": action, "token_index": token_index})
    return web.json_response({"queued": True})


async def post_audio_stop(request: web.Request) -> web.Response:
    return await _post_audio_control(request, "audio_stop")


async def post_audio_skip(request: web.Request) -> web.Response:
    return await _post_audio_control(request, "audio_skip")


async def post_audio_loop(request: web.Request) -> web.Response:
    """Queue a loop mode change for the running bot."""

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    mode = body.get("mode")

    errors: list[str] = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    else:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)
    if mode not in LOOP_MODES:
        errors.append("mode must be one of: off, track, queue")

    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {"action": "audio_loop", "token_index": token_index, "mode": mode}
    )
    return web.json_response({"queued": True})


async def post_audio_replay(request: web.Request) -> web.Response:
    """Queue a replay of the current track for the running bot."""

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    if not _is_int(token_index) or token_index < 0:
        return _validation_error(
            ["token_index must be a non-negative integer"]
        )
    token_error = _token_index_error(token_index)
    if token_error is not None:
        return _validation_error([token_error])

    queue.enqueue({"action": "audio_replay", "token_index": token_index})
    return web.json_response({"queued": True})


async def post_audio_forcefix(request: web.Request) -> web.Response:
    """Queue a full voice reconnect and playback restore."""

    return await _post_audio_control(request, "audio_forcefix")


async def post_audio_filters(request: web.Request) -> web.Response:
    """Queue an audio filter change for the running bot."""

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    filters = body.get("filters")
    bass_level = body.get("bass_level")

    errors: list[str] = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    else:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)
    if not isinstance(filters, list):
        errors.append("filters must be a list of strings")
    elif len(filters) > AUDIO_FILTERS_MAX:
        errors.append("filters must contain at most 10 entries")
    elif any(
        not isinstance(name, str) or name not in AUDIO_FILTER_KEYS
        for name in filters
    ):
        errors.append("filters contains an unsupported filter")
    if bass_level is not None and (
        not _is_int(bass_level)
        or not BASS_LEVEL_MIN <= bass_level <= BASS_LEVEL_MAX
    ):
        errors.append("bass_level must be an integer between 1 and 999")

    if errors:
        return _validation_error(errors)

    command: dict[str, Any] = {
        "action": "audio_filters",
        "token_index": token_index,
        "filters": list(filters),
    }
    if bass_level is not None:
        command["bass_level"] = bass_level
    queue.enqueue(command)
    return web.json_response({"queued": True})


async def post_audio_volume(request: web.Request) -> web.Response:
    """Queue a playback volume change for the running bot."""

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    volume = body.get("volume")

    errors: list[str] = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    else:
        token_error = _token_index_error(token_index)
        if token_error is not None:
            errors.append(token_error)
    if not _is_int(volume) or not VOLUME_MIN <= volume <= VOLUME_MAX:
        errors.append("volume must be an integer between 0 and 200")

    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {
            "action": "audio_volume",
            "token_index": token_index,
            "volume": volume,
        }
    )
    return web.json_response({"queued": True})


async def get_audio_queue(request: web.Request) -> web.Response:
    token_index: int | None = None
    raw_token_index = request.query.get("token_index")
    if raw_token_index is not None:
        if (
            not _is_digits(raw_token_index)
            or len(raw_token_index) > TOKEN_INDEX_MAX_DIGITS
        ):
            return _validation_error(
                ["token_index must be a non-negative integer"]
            )
        token_index = int(raw_token_index)

    state = read_voice_state(request.app[VOICE_STATE_PATH_KEY])
    audio = _audio_section(state)
    if token_index is None:
        return web.json_response({"audio": audio})
    return web.json_response({"audio": audio.get(str(token_index)) or {}})


def register(app) -> None:
    """Attach the audio playback routes to the dashboard application."""

    app.router.add_post(PLAY_PATH, post_voice_play)
    app.router.add_post(SEARCH_PATH, post_voice_search)
    app.router.add_post(STOP_PATH, post_audio_stop)
    app.router.add_post(SKIP_PATH, post_audio_skip)
    app.router.add_post(LOOP_PATH, post_audio_loop)
    app.router.add_post(REPLAY_PATH, post_audio_replay)
    app.router.add_post(FORCEFIX_PATH, post_audio_forcefix)
    app.router.add_post(FILTERS_PATH, post_audio_filters)
    app.router.add_post(VOLUME_PATH, post_audio_volume)
    app.router.add_get(QUEUE_PATH, get_audio_queue)
