"""Voice state actions: self mute/deafen and channel moves.

These handlers are discovered by :mod:`src.voice_actions` and invoked from the
Voice cog's dashboard command loop. Every operation goes through the gateway
connector (opcode 4) — no REST calls.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ACTIONS = ["voice_state", "move"]


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_digits(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isdigit()
    )


def _known_token_indices(manager, cog) -> list[int]:
    """Union of live gateway indices and configured voice token indices."""

    indices: set[int] = set()

    connectors = getattr(manager, "gateway_connectors", None)
    if isinstance(connectors, dict):
        for key in connectors.keys():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indices.add(index)

    try:
        tokens = cog.bot.config.get("voice_token", [])
    except Exception:
        tokens = []
    if isinstance(tokens, list):
        indices.update(range(len(tokens)))

    return sorted(indices)


def _audio_owner(index, manager) -> bool:
    try:
        checker = getattr(manager, "is_main_index", None)
        if callable(checker) and checker(index):
            return False
    except Exception:
        pass
    try:
        from src.voice_audio import audio_streamer
    except Exception:
        return False
    try:
        return bool(audio_streamer.has_client(index))
    except Exception:
        return False


def _token_label(index, manager) -> str:
    try:
        from src.voice_audio import token_label

        return token_label(index, manager)
    except Exception:
        return f"#{index}"


async def _apply_voice_state(command, cog, manager) -> None:
    if not isinstance(command, dict):
        logger.warning("voice_state: command must be an object")
        return

    guild_id = command.get("guild_id")
    if not _is_digits(guild_id):
        logger.warning("voice_state: invalid guild_id %r", guild_id)
        return

    mute = command.get("mute")
    deaf = command.get("deaf")
    if mute is not None and not isinstance(mute, bool):
        logger.warning("voice_state: mute must be a boolean")
        return
    if deaf is not None and not isinstance(deaf, bool):
        logger.warning("voice_state: deaf must be a boolean")
        return
    if mute is None and deaf is None:
        logger.warning("voice_state: mute or deaf is required")
        return

    async def apply_one(index):
        if _audio_owner(index, manager):
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.set_self_state(
                    index, self_mute=mute, self_deaf=deaf
                )
            except Exception:
                ok = False
            if ok:
                return True
        return bool(
            manager.update_voice_state(
                index, guild_id, self_mute=mute, self_deaf=deaf
            )
        )

    if command.get("all") is True:
        failed = []
        for index in _known_token_indices(manager, cog):
            if not await apply_one(index):
                failed.append(_token_label(index, manager))
        if failed:
            logger.warning(
                "voice_state: no active voice session for token(s) %s", failed
            )
        return

    token_index = command.get("token_index")
    if not _is_int(token_index) or token_index < 0:
        logger.warning("voice_state: invalid token_index %r", token_index)
        return
    if not await apply_one(token_index):
        logger.warning(
            "voice_state: token %s has no active voice session",
            _token_label(token_index, manager),
        )


async def _apply_move(command, manager) -> None:
    if not isinstance(command, dict):
        logger.warning("move: command must be an object")
        return

    token_index = command.get("token_index")
    guild_id = command.get("guild_id")
    channel_id = command.get("channel_id")
    if not _is_int(token_index) or token_index < 0:
        logger.warning("move: invalid token_index %r", token_index)
        return
    if not _is_digits(guild_id):
        logger.warning("move: invalid guild_id %r", guild_id)
        return
    if not _is_digits(channel_id):
        logger.warning("move: invalid channel_id %r", channel_id)
        return

    if _audio_owner(token_index, manager):
        try:
            from src.voice_audio import audio_streamer

            ok = await audio_streamer.move_to(token_index, channel_id)
        except Exception:
            ok = False
        if not ok:
            logger.warning(
                "move: token %s has no active audio session",
                _token_label(token_index, manager),
            )
        return

    # Lazy import: cogs.voice imports this package at module load time.
    from src.voice_actions.autoroom import (
        clear_expected,
        expect_move,
        get_auto_room_config,
        mark_manual,
    )

    expect_move(token_index, guild_id, channel_id)

    try:
        applied = manager.update_voice_state(
            token_index,
            guild_id,
            channel_id=channel_id,
        )
    finally:
        # The expectation is only useful until the move attempt finishes; a
        # failed attempt must not misclassify a later external move.
        clear_expected(token_index, guild_id)

    if applied:
        config = get_auto_room_config()
        if config.get("enabled") and str(guild_id) == str(config.get("guild_id")):
            mark_manual(token_index, guild_id, channel_id)


async def handle(action, command, cog):
    """Dispatch one voice state action; never raises into the command loop."""

    try:
        # Lazy import: cogs.voice imports this package at module load time.
        from cogs.voice import voice_manager
    except Exception:
        logger.exception("Voice state action %r could not load voice_manager", action)
        return

    try:
        if action == "voice_state":
            await _apply_voice_state(command, cog, voice_manager)
        elif action == "move":
            await _apply_move(command, voice_manager)
    except Exception:
        logger.exception("Voice state action %r failed", action)
