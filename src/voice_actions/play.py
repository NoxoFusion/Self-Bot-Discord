"""Dashboard audio playback actions backed by :mod:`src.voice_audio`.

Contract (see :mod:`src.voice_actions`):

* ``ACTIONS`` lists the dashboard action names this module handles.
* ``handle(action, command, cog)`` performs the action and never raises.

Payloads::

    play        {"token_index": int, "guild_id": str, "channel_id": str,
                 "query": str}          # 1-300 characters; guild_id optional
    audio_stop  {"token_index": int}
    audio_skip  {"token_index": int}
    audio_loop  {"token_index": int, "mode": "off"|"track"|"queue"}
    audio_replay {"token_index": int}
    audio_queue {"token_index": int}    # logs the streamer snapshot
    audio_filters {"token_index": int, "filters": list[str],
                   "bass_level": int}   # bass_level optional, 1-999
    audio_volume {"token_index": int, "volume": int}  # 0-200 percent
    audio_forcefix {"token_index": int}  # reconnect and restore playback

``play`` hands the guild over to the audio client inside
:meth:`src.voice_audio.AudioStreamer.play`.  The raw signaling connector is
released there, under the client lock, only once playback is actually being
set up.  The dashboard handler must not leave the channel first: if playback
fails, the token would already have been kicked out of voice.
"""

from __future__ import annotations

import logging

from src.voice_audio import audio_streamer, token_label

logger = logging.getLogger(__name__)

ACTIONS = [
    "play",
    "audio_stop",
    "audio_skip",
    "audio_loop",
    "audio_replay",
    "audio_queue",
    "audio_filters",
    "audio_volume",
    "audio_forcefix",
]

MAX_QUERY_LENGTH = 300


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_digits(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isdigit()
    )


def _token_index(command) -> int | None:
    if not isinstance(command, dict):
        return None
    index = command.get("token_index")
    if not _is_int(index) or index < 0:
        return None
    return index


def _is_inactive_error(exc: BaseException) -> bool:
    """Return ``True`` for the "client not created yet" RuntimeErrors."""

    message = str(exc)
    return "is not active" in message or "is not connected" in message


async def _handle_play(command) -> None:
    if not isinstance(command, dict):
        logger.warning("play: command must be an object")
        return

    index = _token_index(command)
    if index is None:
        logger.warning("play: invalid token_index %r", command.get("token_index"))
        return

    guild_id = command.get("guild_id")
    channel_id = command.get("channel_id")
    query = command.get("query")
    if guild_id not in (None, "") and not _is_digits(guild_id):
        logger.warning("play: invalid guild_id %r", guild_id)
        return
    if not _is_digits(channel_id):
        logger.warning("play: invalid channel_id %r", channel_id)
        return
    if not isinstance(query, str):
        logger.warning("play: query must be a string")
        return
    query = query.strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        logger.warning(
            "play: query must be 1-%s characters", MAX_QUERY_LENGTH
        )
        return

    try:
        result = await audio_streamer.play(
            index, guild_id or "", channel_id, query
        )
    except Exception:
        logger.exception(
            "play: audio streamer failed for token %s", token_label(index)
        )
        return

    title = result.get("title") if isinstance(result, dict) else query
    position = result.get("position") if isinstance(result, dict) else "?"
    logger.info(
        "Voice audio %s queued %r at position %s",
        token_label(index),
        title,
        position,
    )


async def _handle_loop(command) -> None:
    if not isinstance(command, dict):
        logger.warning("audio_loop: command must be an object")
        return

    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_loop: invalid token_index %r", command.get("token_index")
        )
        return

    mode = command.get("mode")
    if mode not in {"off", "track", "queue"}:
        logger.warning("audio_loop: invalid mode %r", mode)
        return

    try:
        await audio_streamer.set_loop(index, mode)
    except Exception:
        logger.exception("audio_loop: failed for token %s", token_label(index))
        return
    logger.info("Voice audio %s loop mode set to %r", token_label(index), mode)


async def _handle_replay(command) -> None:
    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_replay: invalid token_index %r",
            command.get("token_index") if isinstance(command, dict) else None,
        )
        return

    try:
        replayed = await audio_streamer.replay(index)
    except Exception:
        logger.exception(
            "audio_replay: failed for token %s", token_label(index)
        )
        return
    if not replayed:
        logger.info(
            "Voice audio %s: nothing playing to replay", token_label(index)
        )
        return
    logger.info(
        "Voice audio %s replayed the current track", token_label(index)
    )


async def _handle_filters(command) -> None:
    if not isinstance(command, dict):
        logger.warning("audio_filters: command must be an object")
        return

    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_filters: invalid token_index %r",
            command.get("token_index"),
        )
        return

    filters = command.get("filters")
    if not isinstance(filters, list) or not all(
        isinstance(item, str) for item in filters
    ):
        logger.warning("audio_filters: filters must be a list of strings")
        return

    bass_level = None
    if "bass_level" in command:
        bass_level = command.get("bass_level")
        if not _is_int(bass_level):
            logger.warning(
                "audio_filters: invalid bass_level %r", bass_level
            )
            return

    try:
        result = await audio_streamer.apply_filters(
            index, filters, bass_level
        )
    except RuntimeError as exc:
        if _is_inactive_error(exc):
            logger.warning(
                "audio_filters: token %s is not active", token_label(index)
            )
        else:
            logger.exception(
                "audio_filters: failed for token %s", token_label(index)
            )
        return
    except Exception:
        logger.exception(
            "audio_filters: failed for token %s", token_label(index)
        )
        return

    if isinstance(result, dict) and isinstance(result.get("filters"), list):
        count = len(result["filters"])
    else:
        count = len(filters)
    logger.info(
        "Voice audio %s filters updated (%s active)",
        token_label(index),
        count,
    )


async def _handle_volume(command) -> None:
    if not isinstance(command, dict):
        logger.warning("audio_volume: command must be an object")
        return

    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_volume: invalid token_index %r",
            command.get("token_index"),
        )
        return

    volume = command.get("volume")
    if not _is_int(volume) or not 0 <= volume <= 200:
        logger.warning("audio_volume: invalid volume %r", volume)
        return

    try:
        value = await audio_streamer.set_volume(index, volume)
    except RuntimeError as exc:
        if _is_inactive_error(exc):
            logger.warning(
                "audio_volume: token %s is not active", token_label(index)
            )
        else:
            logger.exception(
                "audio_volume: failed for token %s", token_label(index)
            )
        return
    except Exception:
        logger.exception(
            "audio_volume: failed for token %s", token_label(index)
        )
        return

    logger.info(
        "Voice audio %s volume set to %s%%", token_label(index), value
    )


async def _handle_forcefix(command) -> None:
    if not isinstance(command, dict):
        logger.warning("audio_forcefix: command must be an object")
        return

    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_forcefix: invalid token_index %r",
            command.get("token_index"),
        )
        return

    try:
        result = await audio_streamer.forcefix(index)
    except RuntimeError as exc:
        if _is_inactive_error(exc):
            logger.warning(
                "audio_forcefix: token %s is not active", token_label(index)
            )
        else:
            logger.exception(
                "audio_forcefix: failed for token %s", token_label(index)
            )
        return
    except Exception:
        logger.exception(
            "audio_forcefix: failed for token %s", token_label(index)
        )
        return

    title = result.get("title") if isinstance(result, dict) else None
    logger.info(
        "Voice audio %s reconnected and restored %r", token_label(index), title
    )


async def _handle_simple(command, method: str) -> None:
    index = _token_index(command)
    if index is None:
        logger.warning(
            "%s: invalid token_index %r",
            method,
            command.get("token_index") if isinstance(command, dict) else None,
        )
        return
    try:
        await getattr(audio_streamer, method)(index)
    except Exception:
        logger.exception(
            "Voice audio %s failed for token %s", method, token_label(index)
        )


def _handle_queue(command) -> None:
    index = _token_index(command)
    if index is None:
        logger.warning(
            "audio_queue: invalid token_index %r",
            command.get("token_index") if isinstance(command, dict) else None,
        )
        return
    try:
        state = audio_streamer.state()
    except Exception:
        logger.exception("audio_queue: could not read the audio state")
        return
    logger.info("Voice audio state: %s", state)


async def handle(action, command, cog) -> None:
    """Dispatch one audio action; never raises into the command loop."""

    try:
        if action == "play":
            await _handle_play(command)
        elif action == "audio_stop":
            await _handle_simple(command, "stop")
        elif action == "audio_skip":
            await _handle_simple(command, "skip")
        elif action == "audio_loop":
            await _handle_loop(command)
        elif action == "audio_replay":
            await _handle_replay(command)
        elif action == "audio_queue":
            _handle_queue(command)
        elif action == "audio_filters":
            await _handle_filters(command)
        elif action == "audio_volume":
            await _handle_volume(command)
        elif action == "audio_forcefix":
            await _handle_forcefix(command)
    except Exception:
        logger.exception("Voice audio action %r failed", action)
