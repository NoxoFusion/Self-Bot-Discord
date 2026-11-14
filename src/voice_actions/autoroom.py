"""Voice action: Auto-Room mode.

Leader tokens (the first ``leader_count`` tokens) are parked in a lobby
channel. When an external server bot moves a leader into a generated room,
every idle token is distributed round-robin across the rooms currently
occupied by the leaders.

The dashboard queues ``{"action": "auto_room", ...}`` commands; the Voice cog
dispatches them here through :func:`src.voice_actions.dispatch_extra`.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

ACTIONS = ["auto_room"]

DEFAULT_AUTO_ROOM = {
    "enabled": False,
    "guild_id": None,
    "lobby_channel_id": None,
    "leader_count": 1,
    "manual": [],
}

# Module-level live config; mirrored into voice_state.json through the Voice
# cog's writer so the dashboard can read it without an in-process bridge.
AUTO_ROOM = dict(DEFAULT_AUTO_ROOM)

SNOWFLAKE_MIN_LENGTH = 17
SNOWFLAKE_MAX_LENGTH = 20
MAX_LEADERS = 5

# Tokens moved manually from the dashboard are held back from distribution.
# Maps token index -> guild id where the manual move happened.
_MANUAL_HOLD: dict[int, str] = {}
# Maps token index -> manual destination channel (for the dashboard badge and
# so that channel is never mistaken for an auto-room).
_MANUAL_CHANNEL: dict[int, str] = {}

# Dashboard-initiated moves are announced here before they happen. When the
# gateway confirms the move, `_on_leader_moved` recognizes it as a manual move
# instead of an external auto-room move.
_EXPECTED: dict[tuple[int, str], dict] = {}
EXPECTED_TTL = 30.0


def mark_manual(index: int, guild_id: str, channel_id: str | None = None) -> None:
    """Remember that ``index`` was moved manually and must not be redistributed.

    ``channel_id`` records the manual destination so that channel is never
    treated as an auto-room while this hold is active.
    """

    try:
        token_index = int(index)
    except (TypeError, ValueError):
        logger.warning("auto_room: invalid manual token index %r", index)
        return
    lobby = AUTO_ROOM.get("lobby_channel_id")
    if channel_id is not None and lobby and str(channel_id) == str(lobby):
        # The lobby is parking, never a manual destination.
        _MANUAL_HOLD.pop(token_index, None)
        _MANUAL_CHANNEL.pop(token_index, None)
        return
    _MANUAL_HOLD[token_index] = str(guild_id)
    if channel_id is not None:
        _MANUAL_CHANNEL[token_index] = str(channel_id)
    else:
        _MANUAL_CHANNEL.pop(token_index, None)


def clear_manual(index: int) -> None:
    """Release a manual hold so ``index`` can be distributed again."""

    try:
        token_index = int(index)
    except (TypeError, ValueError):
        return
    _MANUAL_HOLD.pop(token_index, None)
    _MANUAL_CHANNEL.pop(token_index, None)


def is_manual(index: int) -> bool:
    """Return ``True`` when ``index`` is currently held by a manual move."""

    try:
        return int(index) in _MANUAL_HOLD
    except (TypeError, ValueError):
        return False


def manual_entries() -> list[dict]:
    """Return manual holds for the dashboard state snapshot."""

    entries = []
    for index in sorted(_MANUAL_HOLD):
        guild_id = _MANUAL_HOLD.get(index)
        channel_id = _MANUAL_CHANNEL.get(index)
        if not guild_id or not channel_id:
            continue
        entries.append(
            {
                "index": index,
                "guild_id": str(guild_id),
                "channel_id": str(channel_id),
            }
        )
    return entries


def get_auto_room_config() -> dict:
    """Return a copy of the current config for the dashboard state snapshot."""

    config = dict(AUTO_ROOM)
    config["manual"] = manual_entries()
    return config


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_snowflake(value) -> bool:
    """Return ``True`` for a 17-20 digit Discord snowflake string."""

    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and SNOWFLAKE_MIN_LENGTH <= len(value) <= SNOWFLAKE_MAX_LENGTH
    )


def expect_move(index, guild_id, channel_id, ttl: float = EXPECTED_TTL) -> None:
    """Announce that ``index`` is about to be moved by the dashboard.

    The gateway confirmation arrives asynchronously; recording the expected
    destination lets ``_on_leader_moved`` tell a user move apart from an
    external server bot moving a leader into a generated room.
    """

    try:
        token_index = int(index)
    except (TypeError, ValueError):
        return
    if not _is_snowflake(guild_id) or not _is_snowflake(channel_id):
        return
    _EXPECTED[(token_index, str(guild_id))] = {
        "channel_id": str(channel_id),
        "expires_at": time.monotonic() + max(0.0, float(ttl)),
    }


def _consume_expected(index, guild_id, channel_id) -> bool:
    """Return ``True`` when this move matches a fresh dashboard expectation."""

    key = (index, str(guild_id))
    entry = _EXPECTED.get(key)
    if not entry:
        return False
    if entry["expires_at"] <= time.monotonic():
        _EXPECTED.pop(key, None)
        return False
    if entry["channel_id"] != str(channel_id):
        return False
    _EXPECTED.pop(key, None)
    return True


def handle_connected(index, guild_id, channel_id) -> None:
    """Consume a dashboard expectation confirmed by ``on_voice_connected``.

    Dashboard joins/moves clear the connector's confirmed-channel cache, so
    Discord's next VOICE_STATE_UPDATE arrives as a first confirmation and
    fires ``on_voice_connected`` instead of ``on_voice_moved``.
    """

    if not _consume_expected(index, guild_id, channel_id):
        return
    config = AUTO_ROOM
    if not config.get("enabled") or str(guild_id) != str(config.get("guild_id")):
        # The expectation is consumed, but a channel in another guild must
        # not create a global manual hold.
        return
    mark_manual(index, guild_id, channel_id)


def clear_expected(index, guild_id=None) -> None:
    """Drop a pending dashboard expectation for one token (or one guild)."""

    try:
        token_index = int(index)
    except (TypeError, ValueError):
        return
    if guild_id is None:
        for key in [key for key in _EXPECTED if key[0] == token_index]:
            _EXPECTED.pop(key, None)
        return
    _EXPECTED.pop((token_index, str(guild_id)), None)


def _validate(command) -> dict | None:
    """Validate a dashboard command; return a normalized config or ``None``."""

    if not isinstance(command, dict):
        logger.warning("auto_room: command must be an object")
        return None

    enabled = command.get("enabled")
    guild_id = command.get("guild_id")
    lobby_channel_id = command.get("lobby_channel_id")
    leader_count = command.get("leader_count")

    if not isinstance(enabled, bool):
        logger.warning("auto_room: enabled must be a boolean")
        return None
    if not _is_snowflake(guild_id):
        logger.warning("auto_room: invalid guild_id %r", guild_id)
        return None
    if not _is_snowflake(lobby_channel_id):
        logger.warning("auto_room: invalid lobby_channel_id %r", lobby_channel_id)
        return None
    if not _is_int(leader_count) or not 1 <= leader_count <= MAX_LEADERS:
        logger.warning("auto_room: invalid leader_count %r", leader_count)
        return None

    return {
        "enabled": enabled,
        "guild_id": guild_id,
        "lobby_channel_id": lobby_channel_id,
        "leader_count": leader_count,
    }


def round_robin_assign(followers, rooms) -> dict:
    """Assign follower token indices to rooms round-robin.

    ``followers`` and ``rooms`` are ordered; the first follower goes to the
    first room, and the assignment wraps around when there are more followers
    than rooms.
    """

    try:
        follower_list = [int(index) for index in followers]
    except (TypeError, ValueError):
        logger.warning("auto_room: followers must be token indices")
        return {}

    room_list = [str(room) for room in rooms if room]
    if not follower_list or not room_list:
        return {}

    return {
        index: room_list[position % len(room_list)]
        for position, index in enumerate(follower_list)
    }


def _manager():
    """Lazy import: ``cogs.voice`` imports this package at module load time."""

    try:
        from cogs.voice import voice_manager

        return voice_manager
    except Exception:
        logger.exception("auto_room: could not load voice_manager")
        return None


def _manager_indices(manager) -> list[int]:
    getter = getattr(manager, "get_all_voice_indices", None)
    if callable(getter):
        try:
            indices = [int(index) for index in getter()]
            return sorted({index for index in indices if index >= 0})
        except Exception:
            logger.exception("auto_room: get_all_voice_indices failed")

    connectors = getattr(manager, "gateway_connectors", None) or {}
    indices = set()
    for key in connectors:
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            indices.add(index)
    return sorted(indices)


def _set_move_callback(manager, callback) -> None:
    default_setter = getattr(manager, "set_default_on_voice_moved", None)
    if callable(default_setter):
        try:
            default_setter(callback)
        except Exception:
            logger.exception("auto_room: could not set the default move callback")

    setter = getattr(manager, "set_callbacks", None)
    if not callable(setter):
        logger.warning("auto_room: manager has no set_callbacks()")
        return

    legacy_setter = getattr(manager, "set_legacy_on_voice_moved", None)
    gateway_indices = set(_manager_indices(manager))
    for index in gateway_indices:
        try:
            setter(index, on_voice_moved=callback)
        except Exception:
            logger.exception(
                "auto_room: could not set move callback for token #%s", index
            )
        if callable(legacy_setter):
            try:
                legacy_setter(index, callback)
            except Exception:
                logger.exception(
                    "auto_room: could not set legacy move callback for token #%s",
                    index,
                )

    # Legacy-only tokens have no gateway index; update their connectors too.
    legacy_indices = set()
    for key in getattr(manager, "voice_connectors", {}) or {}:
        try:
            legacy_indices.add(int(str(key).split("_", 1)[0]))
        except (TypeError, ValueError):
            continue
    if callable(legacy_setter):
        for index in sorted(legacy_indices - gateway_indices):
            try:
                legacy_setter(index, callback)
            except Exception:
                logger.exception(
                    "auto_room: could not set legacy move callback for token #%s",
                    index,
                )


def _leader_room_channels(
    guild_id: str, leader_count: int, lobby_channel_id: str, manager
) -> list[str]:
    """Distinct non-lobby channels currently occupied by leader tokens."""

    rooms: list[str] = []
    for index in range(leader_count):
        try:
            connections = manager.get_all_voice(index) or {}
        except Exception:
            logger.exception("auto_room: could not read token #%s voice", index)
            continue

        for connection in connections.values():
            if not getattr(connection, "voice_connected", False):
                continue
            if str(getattr(connection, "guild_id", "")) != guild_id:
                continue
            channel_id = getattr(connection, "channel_id", None)
            if not channel_id:
                continue
            channel_id = str(channel_id)
            if channel_id == lobby_channel_id:
                continue
            if _MANUAL_CHANNEL.get(index) == channel_id:
                # The user parked this leader here; it is not an auto-room.
                continue
            if channel_id not in rooms:
                rooms.append(channel_id)
    return rooms


def _follower_indices(manager, leader_count: int) -> list[int]:
    """Token indices with no active voice connection, excluding leaders."""

    leaders = set(range(leader_count))
    followers: list[int] = []
    for index in _manager_indices(manager):
        if index in leaders:
            continue
        try:
            connections = manager.get_all_voice(index)
        except Exception:
            logger.exception("auto_room: could not read token #%s voice", index)
            continue
        if not connections:
            followers.append(index)
    return followers


def _move_token(manager, index, guild_id: str, channel_id: str) -> bool:
    """Move a token, joining the channel when it has no voice context yet.

    ``update_voice_state`` only moves a connector that already holds the
    guild; idle followers need a join. The join fallback keeps the primary
    dashboard path (opcode 4 through ``update_voice_state``) intact.
    """

    try:
        applied = manager.update_voice_state(
            index, guild_id, channel_id=channel_id
        )
    except Exception:
        logger.exception(
            "auto_room: could not move token #%s to channel %s",
            index,
            channel_id,
        )
        applied = False

    if applied:
        return True

    getter = getattr(manager, "get_gateway", None)
    if not callable(getter):
        return False
    try:
        gateway = getter(index)
    except Exception:
        logger.exception("auto_room: could not read gateway for token #%s", index)
        return False

    if not getattr(gateway, "connected", False):
        return False

    joiner = getattr(gateway, "join_voice", None)
    if not callable(joiner):
        return False

    try:
        if hasattr(gateway, "gateway_only"):
            gateway.gateway_only = False
        joiner(guild_id, channel_id)
        return True
    except Exception:
        logger.exception(
            "auto_room: could not join token #%s to channel %s",
            index,
            channel_id,
        )
        return False


def _is_streaming(index) -> bool:
    """Return ``True`` when the audio streamer is playing or queued for ``index``."""

    try:
        # Lazy import: src.voice_audio pulls in discord.py and yt-dlp.
        from src.voice_audio import audio_streamer

        audio = audio_streamer.state()
    except Exception:
        logger.exception("auto_room: could not read the audio streamer state")
        return False

    entry = audio.get(str(index)) if isinstance(audio, dict) else None
    return bool(entry and (entry.get("playing") or entry.get("queue")))


def distribute(
    guild_id: str, rooms, follower_indices, manager=None
) -> dict:
    """Move idle followers into ``rooms`` round-robin; never raises."""

    try:
        manager = manager or _manager()
        if manager is None:
            return {}

        followers = [
            index
            for index in follower_indices
            if not is_manual(index) and not _is_streaming(index)
        ]
        assignment = round_robin_assign(followers, rooms)
        for index, channel_id in assignment.items():
            _move_token(manager, index, guild_id, channel_id)
        return assignment
    except Exception:
        logger.exception("auto_room: distribution failed")
        return {}


def _on_leader_moved(index, guild_id, old_channel, new_channel) -> None:
    """Gateway callback: a leader changed voice channel."""

    try:
        config = dict(AUTO_ROOM)
        if not config.get("enabled"):
            return

        guild_id = str(guild_id)
        if guild_id != config.get("guild_id"):
            return

        leader_count = config.get("leader_count") or 0
        if not _is_int(index) or index < 0 or index >= leader_count:
            return

        if _consume_expected(index, guild_id, new_channel):
            # The dashboard moved this leader. The destination is a manual
            # channel, not an auto-room, so followers must stay put.
            if str(new_channel) != str(config.get("lobby_channel_id")):
                mark_manual(index, guild_id, new_channel)
                _write_state(None)
            return

        # An external server bot moved the leader into a generated room, so
        # this leader is back in the auto-room cycle.
        was_manual = is_manual(index)
        clear_manual(index)
        if was_manual:
            _write_state(None)

        manager = _manager()
        if manager is None:
            return

        rooms = _leader_room_channels(
            guild_id,
            leader_count,
            config.get("lobby_channel_id"),
            manager,
        )
        followers = _follower_indices(manager, leader_count)
        distribute(guild_id, rooms, followers, manager=manager)
    except Exception:
        logger.exception("auto_room: leader move handling failed")


def _join_leaders(
    guild_id: str, lobby_channel_id: str, leader_count: int, manager
) -> None:
    for index in range(leader_count):
        expect_move(index, guild_id, lobby_channel_id)
        _move_token(manager, index, guild_id, lobby_channel_id)


def _write_state(cog) -> None:
    """Persist the new config through the Voice cog's state writer."""

    writer = getattr(cog, "_write_voice_state", None)
    if not callable(writer):
        try:
            from cogs.voice import _write_voice_state as writer
        except Exception:
            logger.exception("auto_room: could not load the voice state writer")
            return

    try:
        writer()
    except Exception:
        logger.exception("auto_room: could not persist voice state")


def _enable(config: dict, cog) -> None:
    manager = _manager()
    if manager is None:
        return

    _MANUAL_HOLD.clear()
    _MANUAL_CHANNEL.clear()
    _EXPECTED.clear()
    AUTO_ROOM.update(config)
    _set_move_callback(manager, _on_leader_moved)
    _join_leaders(
        config["guild_id"],
        config["lobby_channel_id"],
        config["leader_count"],
        manager,
    )
    _write_state(cog)


def _disable(cog) -> None:
    manager = _manager()
    if manager is not None:
        _set_move_callback(manager, None)

    _MANUAL_HOLD.clear()
    _MANUAL_CHANNEL.clear()
    _EXPECTED.clear()
    AUTO_ROOM.clear()
    AUTO_ROOM.update(DEFAULT_AUTO_ROOM)
    _write_state(cog)


async def handle(action, command, cog):
    """Dispatch the auto-room action; never raises into the command loop."""

    try:
        if action != "auto_room":
            logger.warning("auto_room: unsupported action %r", action)
            return

        if isinstance(command, dict) and command.get("enabled") is False:
            _disable(cog)
            return

        config = _validate(command)
        if config is None:
            return

        if config["enabled"]:
            _enable(config, cog)
        else:
            _disable(cog)
    except Exception:
        logger.exception("auto_room action failed")
