"""
Voice Control — Voice Manager + Soundboard.
Prefix: {prefix}
"""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path

import aiohttp
from discord.ext import commands, tasks
from src.client_identity import (
    discord_headers,
    session_identity as make_session_identity,
)
from src.command_spool import drain
from src.http_client import api_request
from src.main_voice import MainVoiceBridge
from src.voice_actions import dispatch_extra
from src.voice_connector import VoiceManager

logger = logging.getLogger(__name__)

VOICE_STATE_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "voice_state.json"
)
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
VOICE_COMMANDS_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "voice_commands.json"
)

# Serialize writers: gateway/verify/autoroom threads and the event loop all
# persist this file, and a torn write makes the dashboard see every token as
# offline.
_VOICE_STATE_LOCK = threading.Lock()

# Serialize read-modify-write cycles on config.json.  Evictions run from
# gateway/verify threads while the dashboard backend also writes the file; two
# unlocked evictions would revert each other and lose backend changes.
_CONFIG_LOCK = threading.Lock()


def build_voice_state(manager, token_count):
    """Build the dashboard-facing voice state snapshot."""

    # Lazy import: audio streaming module is optional (deps may be missing).
    try:
        from src.voice_audio import audio_streamer
    except Exception:
        audio_streamer = None

    tokens = []
    for index in range(token_count):
        gateway = manager.get_gateway(index)
        stream_flags = manager.get_stream_flags(index)
        channels = []
        guild_ids = set()

        for connection in (manager.get_all_voice(index) or {}).values():
            if getattr(connection, "voice_connected", False):
                channels.append(str(connection.channel_id))
                guild_id = getattr(connection, "guild_id", None)
                if guild_id:
                    guild_ids.add(str(guild_id))

        entry = {
            "index": index,
            "gateway_ready": manager.is_gateway_ready(index),
            "username": gateway.username if gateway else None,
            "user_id": gateway.user_id if gateway else None,
            "channels": channels,
            "guild_id": next(iter(guild_ids)) if len(guild_ids) == 1 else None,
            "streaming": bool(stream_flags.get("streaming")),
            "video": bool(stream_flags.get("video")),
            "self_mute": bool(getattr(gateway, "self_mute", True))
            if gateway
            else True,
            "self_deaf": bool(getattr(gateway, "self_deaf", False))
            if gateway
            else False,
            "guild_channels": _guild_channels_snapshot(gateway),
        }

        flags = None
        if audio_streamer is not None:
            try:
                flags = audio_streamer.voice_flags(index)
            except Exception:
                flags = None
        entry["audio_active"] = bool(flags.get("audio_active")) if flags else False
        entry["audio_playing"] = bool(flags.get("audio_playing")) if flags else False
        if flags and flags.get("connected"):
            entry["gateway_ready"] = True
            if flags.get("channel_id"):
                entry["channels"] = [str(flags["channel_id"])]
            if flags.get("guild_id"):
                entry["guild_id"] = str(flags["guild_id"])
            entry["self_mute"] = bool(flags.get("self_mute", entry["self_mute"]))
            entry["self_deaf"] = bool(flags.get("self_deaf", entry["self_deaf"]))
            entry["streaming"] = bool(flags.get("self_stream", False))
            entry["video"] = bool(flags.get("self_video", False))

        tokens.append(entry)

    # Lazy import: src.voice_actions imports this package at module load time.
    try:
        from src.voice_actions.autoroom import get_auto_room_config

        auto_room = get_auto_room_config()
    except Exception:
        auto_room = {
            "enabled": False,
            "guild_id": None,
            "lobby_channel_id": None,
            "leader_count": 1,
        }

    audio_state = audio_streamer.state() if audio_streamer is not None else {}

    return {
        "updated_at": time.time(),
        "tokens": tokens,
        "auto_room": auto_room,
        "audio": audio_state,
    }


def _guild_channels_snapshot(gateway) -> dict:
    """Voice/stage channels cached per guild for the dashboard Move picker."""

    snapshot = {}
    cache = getattr(gateway, "guild_channels", None) or {}
    for guild_id, channels in list(cache.items()):
        snapshot[str(guild_id)] = [
            {
                "id": str(channel.get("id")),
                "name": channel.get("name", ""),
                "position": channel.get("position", 0),
            }
            for channel in channels
            if isinstance(channel, dict) and channel.get("id")
        ]
    return snapshot


def _write_voice_state():
    """Persist the current voice state for the dashboard backend."""

    try:
        with _VOICE_STATE_LOCK:
            config_path = CONFIG_PATH
            # Evictions replace config.json while gateway threads run; hold the
            # same lock so a Windows replace cannot race this read.
            with _CONFIG_LOCK:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            tokens = config.get("voice_token", [])
            state = build_voice_state(voice_manager, len(tokens))
            VOICE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path = VOICE_STATE_PATH.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            temp_path.replace(VOICE_STATE_PATH)
    except Exception:
        logger.warning("Voice state write failed", exc_info=True)


def mask_id(user_id: str) -> str:
    """Che USER ID khi hiển thị (khác với mask_token che token)."""
    s = str(user_id or "")
    return f"{s[:4]}...{s[-3:]}" if len(s) > 8 else s or "N/A"


STREAM_INTENT = {}
CAMERA_INTENT = {}
_TOGGLE_TIMES = {}
STREAM_TOGGLE_COOLDOWN = 3.0


def cooldown_ok(action: str, index: int, now: float | None = None) -> bool:
    """Rate-limit toggle theo cặp action:index (mặc định 3s)."""

    current = time.monotonic() if now is None else now
    key = f"{action}:{index}"
    last = _TOGGLE_TIMES.get(key)
    if last is not None and current - last < STREAM_TOGGLE_COOLDOWN:
        return False
    _TOGGLE_TIMES[key] = current
    return True


def apply_stream_toggle(index: int, enable: bool, manager) -> bool:
    """Lưu intent rồi áp dụng stream toggle lên manager."""

    if enable:
        STREAM_INTENT[index] = True
        return bool(manager.start_stream(index))
    STREAM_INTENT.pop(index, None)
    return bool(manager.stop_stream(index))


def apply_camera_toggle(index: int, enable: bool, manager) -> bool:
    """Lưu intent rồi áp dụng camera toggle lên manager."""

    if enable:
        CAMERA_INTENT[index] = True
    else:
        CAMERA_INTENT.pop(index, None)
    return bool(manager.set_camera(index, enable))


voice_manager = VoiceManager()


def _audio_owner(index: int) -> bool:
    """True when the audio engine holds a client for a non-main token."""
    try:
        if voice_manager.is_main_index(index):
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


def _token_label(index: int) -> str:
    """Human label for a token index: ``#0 (alice)`` when known."""
    try:
        from src.voice_audio import token_label

        return token_label(index, voice_manager)
    except Exception:
        return f"#{index}"


# Set by Voice.__init__ so module-level gateway callbacks can evict tokens
# and compare the main account id without a cog reference.
_BOT = None
_MAIN_USER_ID = None

# Serialize verification/boot per token index. Two reloads must never open
# two gateway sessions for the same token at the same time.
_BOOT_LOCKS: dict[int, threading.Lock] = {}
_BOOT_LOCKS_GUARD = threading.Lock()


def _boot_lock(index):
    with _BOOT_LOCKS_GUARD:
        lock = _BOOT_LOCKS.get(index)
        if lock is None:
            lock = threading.Lock()
            _BOOT_LOCKS[index] = lock
        return lock


def _identity_for_index(index):
    """Per-session identity of the connector that owns ``index``."""

    try:
        gateway = voice_manager.get_gateway(index)
        return getattr(gateway, "session_identity", None)
    except Exception:
        return None


def _evict_voice_token(index, reason):
    """Remove a dead token from the pool.

    The entry is replaced with an empty string (not popped) so every other
    token keeps its index — the backend and the bot both rely on stable
    indices.  Never logs the token itself.
    """

    global _BOT
    evicted = False
    try:
        config_path = CONFIG_PATH
        with _CONFIG_LOCK:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            tokens = config.get("voice_token")
            if not isinstance(tokens, list) or not 0 <= index < len(tokens):
                return
            if not str(tokens[index] or "").strip():
                return  # already evicted
            connector = voice_manager.gateway_connectors.get(index)
            expected = getattr(connector, "token", None)
            if expected and str(tokens[index]).strip() != str(expected).strip():
                # The config changed underneath us (backend purge + reload).
                # The reload will rebuild the pool; never clear somebody else's
                # slot.
                logger.warning(
                    "Voice token %s config changed — skipping eviction",
                    _token_label(index),
                )
                return
            tokens[index] = ""
            temp = config_path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(config, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            temp.replace(config_path)
            evicted = True
            bot = _BOT
            if bot is not None and isinstance(getattr(bot, "config", None), dict):
                bot.config["voice_token"] = tokens
        logger.warning(
            "🗑 Voice token %s removed from the pool (%s)",
            _token_label(index),
            reason,
        )
    except Exception as exc:
        logger.warning(
            "Voice token %s eviction failed: %s", _token_label(index), exc
        )
    finally:
        if evicted:
            # Cleanup runs outside the config lock: stopping a connector can
            # block and must never hold up another eviction or backend write.
            connector = voice_manager.gateway_connectors.pop(index, None)
            if connector is not None:
                try:
                    connector.stop()
                except Exception:
                    pass
            _write_voice_state()


def _on_ready(idx, user_id, username):
    logger.info(
        f"Voice token {_token_label(idx)} gateway ready ({mask_id(user_id)})"
    )
    if _MAIN_USER_ID and str(user_id) == _MAIN_USER_ID:
        logger.warning(
            "Voice token %s is a different session of the MAIN account — "
            "evicting it to avoid a duplicate gateway session",
            _token_label(idx),
        )
        _evict_voice_token(idx, "main-account session token")
        return
    _write_voice_state()


def _on_token_dead(idx, close_code):
    logger.warning(
        "Voice token %s died (gateway close %s) — removing it from the pool",
        _token_label(idx),
        close_code,
    )
    _evict_voice_token(idx, f"gateway close {close_code}")


def _schedule_intent_retry(delay, callback, *args):
    """Run ``callback`` after ``delay`` on the loop when one is running.

    Gateway-thread callbacks (secondary tokens) have no running loop, so they
    keep using a thread timer.  The main bridge's callbacks run inside the
    event loop, where ``loop.call_later`` keeps the scheduled ``create_task``
    on the correct thread.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.call_later(delay, callback, *args)
    else:
        threading.Timer(delay, callback, args=args).start()


def _on_voice_connected(idx, guild_id, channel_id):
    logger.info(
        f"Voice token {_token_label(idx)} joined guild {guild_id} / channel {channel_id}"
    )
    # Dashboard joins/moves confirm as a first connection (the connector
    # clears its confirmed cache), so auto-room consumes its expectation here.
    try:
        from src.voice_actions.autoroom import handle_connected

        handle_connected(idx, guild_id, channel_id)
    except Exception:
        logger.debug("Auto-room connected hook failed", exc_info=True)
    # Re-apply intent sau khi voice đã ổn định (1.5s) — sống qua reconnect
    if STREAM_INTENT.get(idx):
        _schedule_intent_retry(1.5, voice_manager.start_stream, idx)
    if CAMERA_INTENT.get(idx):
        _schedule_intent_retry(1.5, voice_manager.set_camera, idx, True)
    _write_voice_state()


def _on_voice_disconnected(idx, guild_id, channel_id):
    logger.info(f"Voice token {_token_label(idx)} left guild {guild_id}")
    _write_voice_state()


API_BASE = "https://discord.com/api/v10"


async def _probe_token_identity(token, identity):
    """GET /users/@me with a session private to the calling thread.

    Verification runs in a worker thread with its own event loop.  The shared
    session in src.http_client is bound to the bot loop and would be closed and
    recreated by every concurrent check, so each probe owns its own session.
    """

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        headers = discord_headers(identity)
        headers["Authorization"] = token
        async with http.get(f"{API_BASE}/users/@me", headers=headers) as response:
            try:
                data = await response.json(content_type=None)
            except Exception:
                data = None
            return response.status, data


async def _resolve_channel(token: str, channel_id: str, identity=None):
    """GET /channels/{id} → (guild_id hoặc None, HTTP status hoặc None)."""
    status, data = await api_request(
        "GET",
        f"{API_BASE}/channels/{channel_id}",
        token=token,
        session_identity=identity,
    )
    if status == 200 and isinstance(data, dict):
        return data.get("guild_id"), status
    return None, status


def _sound_emoji(sound: dict) -> str:
    """Render emoji của soundboard sound — custom emoji hiển thị đúng hình."""
    emoji_id = sound.get("emoji_id")
    emoji_name = sound.get("emoji_name")
    if emoji_id and emoji_name:
        return f"<:{emoji_name}:{emoji_id}>"
    return emoji_name or ""


class Voice(commands.Cog):
    """Control voice connection + Soundboard."""

    def __init__(self, bot):
        global _BOT, _MAIN_USER_ID
        self.bot = bot
        _BOT = bot
        user = getattr(bot, "user", None)
        _MAIN_USER_ID = str(user.id) if user is not None else None
        self._wire_audio_provider()
        self._boot_tokens()

    def _wire_audio_provider(self):
        """Let the audio streamer reuse the main bot for main-token indices."""

        try:
            from src.voice_audio import audio_streamer

            audio_streamer.set_client_provider(self._audio_client_for)
        except Exception:
            logger.debug("Voice audio provider not wired", exc_info=True)

    def _audio_client_for(self, index):
        if voice_manager.is_main_index(index):
            bridge = voice_manager.get_main_bridge(index)
            return getattr(bridge, "bot", self.bot)

        # Reload window: the bridge may be unregistered for a moment, but the
        # main token still must never get a second gateway session.
        config = getattr(self.bot, "config", None)
        if not isinstance(config, dict):
            return None
        main_token = config.get("token")
        tokens = config.get("voice_token")
        if not isinstance(main_token, str) or not isinstance(tokens, list):
            return None
        try:
            token = tokens[index]
        except (IndexError, TypeError):
            return None
        if isinstance(token, str) and token.strip() == main_token.strip():
            return self.bot
        return None

    def _sync_main_token(self):
        """Remember the main token so VoiceManager refuses duplicate gateways."""

        config = getattr(self.bot, "config", None)
        token = config.get("token") if isinstance(config, dict) else None
        voice_manager.main_token = (
            token.strip() if isinstance(token, str) and token.strip() else None
        )

    def _boot_tokens(self):
        self._sync_main_token()
        config = self.bot.config
        tokens = config.get("voice_token", [])
        if not isinstance(tokens, list) or not tokens:
            return

        main_token = voice_manager.main_token

        for i, token in enumerate(tokens):
            if not isinstance(token, str) or not token.strip():
                continue
            if _audio_owner(i):
                logger.debug(
                    "Voice token %s: audio engine owns the session — skipping gateway boot",
                    _token_label(i),
                )
                continue
            if main_token and token.strip() == main_token:
                # The main token already has a live gateway session.  Booting
                # another one invalidates it (and can force a password reset).
                bridge = MainVoiceBridge(self.bot, i)
                voice_manager.register_main(i, bridge)
                logger.warning(
                    "Voice token %s is the main account — routed through the "
                    "main session (no duplicate gateway)",
                    _token_label(i),
                )
                continue
            if _MAIN_USER_ID:
                threading.Thread(
                    target=self._verify_and_boot,
                    args=(i, token),
                    daemon=True,
                    name=f"voice-verify-{i}",
                ).start()
                continue
            voice_manager.boot_gateway(
                i,
                token,
                on_ready=_on_ready,
                on_token_dead=_on_token_dead,
                telemetry_enabled=bool(
                    self.bot.config.get("voice_telemetry", False)
                ),
            )

    def _verify_and_boot(self, index, token):
        """Reject a different-session token of the main account before boot.

        Waiting for READY is too late: the duplicate gateway session can
        invalidate the main bot's session. Resolve the token owner first with
        the same fingerprint the connector will use.
        """

        with _boot_lock(index):
            identity = make_session_identity()
            try:
                status, data = asyncio.run(_probe_token_identity(token, identity))
            except Exception:
                status, data = None, None

            if status is None:
                # The check did not resolve (network error/timeout).  Booting
                # could duplicate the main account's session and evicting could
                # drop a healthy token, so leave the slot untouched.
                logger.warning(
                    "Voice token %s identity check unresolved — not booting "
                    "and not evicting",
                    _token_label(index),
                )
                return

            if status == 401:
                _evict_voice_token(index, "invalid token (401)")
                return
            if (
                status == 200
                and isinstance(data, dict)
                and _MAIN_USER_ID
                and str(data.get("id")) == _MAIN_USER_ID
            ):
                _evict_voice_token(index, "main-account session token")
                return

            voice_manager.boot_gateway(
                index,
                token,
                on_ready=_on_ready,
                on_token_dead=_on_token_dead,
                telemetry_enabled=bool(
                    self.bot.config.get("voice_telemetry", False)
                ),
                session_identity=identity,
            )

    async def _boot_index(self, index, token):
        """Boot one token for a join, using the startup identity probe.

        The main token is routed through the main session: ``boot_gateway``
        refuses it by value/index and returns the bridge, while the probe would
        evict it as a duplicate main-account session.
        """

        main_token = getattr(voice_manager, "main_token", None)
        is_main = voice_manager.is_main_index(index) or (
            isinstance(main_token, str)
            and bool(main_token.strip())
            and token.strip() == main_token.strip()
        )
        if is_main:
            voice_manager.boot_gateway(
                index=index,
                token=token,
                on_ready=_on_ready,
                on_token_dead=_on_token_dead,
                telemetry_enabled=bool(
                    self.bot.config.get("voice_telemetry", False)
                ),
            )
            return

        # The probe runs in a worker thread (it owns its event loop).
        await asyncio.to_thread(self._verify_and_boot, index, token)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Mirror the main account's own voice state into the dashboard."""

        user = getattr(self.bot, "user", None)
        if user is None or getattr(member, "id", None) != getattr(user, "id", None):
            return

        bridge = voice_manager.get_main_bridge()
        if bridge is None:
            return

        channel = getattr(after, "channel", None) or getattr(before, "channel", None)
        guild = getattr(member, "guild", None) or getattr(channel, "guild", None)
        if guild is None:
            return

        after_channel = getattr(after, "channel", None)
        bridge.handle_state_update(
            str(guild.id),
            str(after_channel.id) if after_channel is not None else None,
            getattr(after, "self_mute", False),
            getattr(after, "self_deaf", False),
            getattr(after, "self_video", False),
            getattr(after, "self_stream", False),
        )
        _write_voice_state()

    def cog_unload(self):
        """Dừng toàn bộ gateway/voice của token phụ khi unload/reload cog."""
        if self._dashboard_commands.is_running():
            self._dashboard_commands.cancel()
        logger.warning(
            "Voice cog unload — all secondary token voice connections are DISCONNECTED; use .reload voice or .join to reconnect"
        )
        voice_manager.stop_all()
        try:
            from src.voice_audio import audio_streamer

            # Keep a reference: a bare create_task can be garbage-collected
            # before close_all() finishes.
            self._close_task = asyncio.create_task(audio_streamer.close_all())
        except Exception:
            pass

    async def cog_load(self):
        self._sync_main_token()
        if not self._dashboard_commands.is_running():
            self._dashboard_commands.start()

    @commands.Cog.listener()
    async def on_ready(self):
        """Restart the dashboard command loop after a bot.run() crash-retry.

        ``cog_load`` runs only once per process; main.py retries ``bot.run()``
        on network crashes and on_ready fires again while the previous loop is
        dead.  Re-sync the main token as well so the duplicate-gateway guard
        keeps working after a reconnect.
        """

        self._sync_main_token()
        if not self._dashboard_commands.is_running():
            self._dashboard_commands.start()

    @tasks.loop(seconds=1)
    async def _dashboard_commands(self):
        """Consume join/leave commands queued by the local dashboard."""

        for command in drain(VOICE_COMMANDS_PATH):
            if not isinstance(command, dict):
                continue
            action = command.get("action")
            if action == "join":
                await self._dashboard_join(command)
            elif action == "leave":
                await self._dashboard_leave(command)
            elif action == "stream":
                await self._dashboard_stream(command)
            elif action == "camera":
                await self._dashboard_camera(command)
            elif action == "reload":
                await self._dashboard_reload()
            else:
                await dispatch_extra(action, command, self)
            _write_voice_state()

    async def _dashboard_reload(self):
        """Reload the root config and reboot all voice gateways."""

        config_path = Path(__file__).resolve().parents[1] / "config.json"
        try:
            new_config = json.loads(
                config_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "Dashboard voice reload failed to read config (%s)",
                type(exc).__name__,
            )
            return

        voice_manager.stop_all()
        await asyncio.sleep(2)
        self.bot.config = new_config
        self._boot_tokens()
        _write_voice_state()

    async def _dashboard_join(self, command):
        token_index = command.get("token_index")
        channels = command.get("channels")
        if not isinstance(token_index, int) or not isinstance(channels, list):
            return

        tokens = self.bot.config.get("voice_token", [])
        if token_index < 0 or token_index >= len(tokens):
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            return

        if _audio_owner(token_index):
            targets = [
                cid
                for cid in channels[:2]
                if isinstance(cid, str) and cid.isdigit()
            ]
            if not targets:
                logger.warning(
                    "Voice token %s: no numeric channel for audio move",
                    _token_label(token_index),
                )
                return
            if len(targets) > 1:
                logger.warning(
                    "Voice token %s: audio session is single-channel — "
                    "using %s (ignored %s)",
                    _token_label(token_index),
                    targets[0],
                    targets[1:],
                )
            try:
                from src.voice_audio import audio_streamer

                ok = False
                for target in targets:
                    ok = await audio_streamer.move_to(token_index, target)
                    if ok:
                        break
            except Exception:
                logger.exception(
                    "Voice token %s: audio move failed",
                    _token_label(token_index),
                )
                return
            if not ok:
                logger.warning(
                    "Voice token %s: audio session could not move to %s",
                    _token_label(token_index),
                    targets,
                )
            return

        if not voice_manager.is_gateway_ready(token_index):
            # Same identity probe as the boot path: a duplicate main-account
            # session must be rejected before the gateway opens, not after
            # READY.
            await self._boot_index(token_index, token)
            for _ in range(3):
                await asyncio.sleep(5)
                if voice_manager.is_gateway_ready(token_index):
                    break
            if not voice_manager.is_gateway_ready(token_index):
                return

        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            return
        resolved = []
        for channel_id in channels[:2]:
            if not isinstance(channel_id, str) or not channel_id.isdigit():
                continue
            guild_id, status = await _resolve_channel(
                token, channel_id, _identity_for_index(token_index)
            )
            if status == 200 and guild_id:
                resolved.append((str(guild_id), channel_id))
            else:
                logger.warning(
                    "Voice token %s: could not resolve channel %s (HTTP %s)",
                    _token_label(token_index), channel_id, status,
                )

        if not resolved:
            logger.warning(
                "Voice token %s: no resolvable channels in %s",
                _token_label(token_index), channels,
            )
            return

        # Discord chỉ cho 1 voice channel / user / guild → giữ channel cuối.
        deduped = {}
        for guild_id, channel_id in resolved:
            previous = deduped.get(guild_id)
            if previous is not None and previous != channel_id:
                logger.warning(
                    "Dashboard voice join token %s: channels %s and %s are in the same "
                    "guild %s — keeping %s (last)",
                    _token_label(token_index), previous, channel_id, guild_id, channel_id,
                )
            deduped[guild_id] = channel_id

        # Single channel → gateway session (stable). Multiple → one session per guild.
        record_manual = None
        try:
            from src.voice_actions.autoroom import (
                clear_expected,
                expect_move,
                get_auto_room_config,
                mark_manual,
            )

            auto_room = get_auto_room_config()
            auto_guild = str(auto_room.get("guild_id") or "")
            auto_enabled = bool(auto_room.get("enabled"))

            def record_manual(guild_id, channel_id, joined):
                # A failed join must not leave a manual hold behind.
                if not joined:
                    clear_expected(token_index, guild_id)
                    return
                if auto_enabled and guild_id == auto_guild:
                    # The user placed this token manually; keep it out of the
                    # auto-room distribution and remember the channel.
                    mark_manual(token_index, guild_id, channel_id)
                    clear_expected(token_index, guild_id)

            for guild_id, channel_id in deduped.items():
                expect_move(token_index, guild_id, channel_id)
        except Exception:
            logger.debug(
                "Auto-room move expectation not recorded", exc_info=True
            )

        if len(deduped) == 1:
            guild_id, channel_id = next(iter(deduped.items()))
            gateway = voice_manager.join_channel_single(
                index=token_index,
                guild_id=guild_id,
                channel_id=channel_id,
                on_voice_connected=_on_voice_connected,
                on_voice_disconnected=_on_voice_disconnected,
                token=token,
            )
            if record_manual is not None:
                record_manual(guild_id, channel_id, gateway is not None)
            return

        for guild_id, channel_id in deduped.items():
            connector = voice_manager.join_channel_multi(
                index=token_index,
                token=token,
                guild_id=guild_id,
                channel_id=channel_id,
                on_voice_connected=_on_voice_connected,
                on_voice_disconnected=_on_voice_disconnected,
            )
            if record_manual is not None:
                record_manual(guild_id, channel_id, connector is not None)
            await asyncio.sleep(2)

    async def _dashboard_stream(self, command):
        token_index = command.get("token_index")
        if not isinstance(token_index, int):
            return

        tokens = self.bot.config.get("voice_token", [])
        if token_index < 0 or token_index >= len(tokens):
            return
        if not cooldown_ok("stream", token_index):
            return

        enable = bool(command.get("enable"))
        if _audio_owner(token_index):
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.set_self_state(
                    token_index, self_stream=enable
                )
            except Exception:
                ok = False
            if ok:
                if enable:
                    STREAM_INTENT[token_index] = True
                else:
                    STREAM_INTENT.pop(token_index, None)
            else:
                _TOGGLE_TIMES.pop(f"stream:{token_index}", None)
                logger.warning(
                    "Voice token %s: audio stream toggle failed",
                    _token_label(token_index),
                )
            _write_voice_state()
            return
        apply_stream_toggle(token_index, enable, voice_manager)
        _write_voice_state()

    async def _dashboard_camera(self, command):
        token_index = command.get("token_index")
        if not isinstance(token_index, int):
            return

        tokens = self.bot.config.get("voice_token", [])
        if token_index < 0 or token_index >= len(tokens):
            return
        if not cooldown_ok("camera", token_index):
            return

        enable = bool(command.get("enable"))
        if _audio_owner(token_index):
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.set_self_state(
                    token_index, self_video=enable
                )
            except Exception:
                ok = False
            if ok:
                if enable:
                    CAMERA_INTENT[token_index] = True
                else:
                    CAMERA_INTENT.pop(token_index, None)
            else:
                _TOGGLE_TIMES.pop(f"camera:{token_index}", None)
                logger.warning(
                    "Voice token %s: audio camera toggle failed",
                    _token_label(token_index),
                )
            _write_voice_state()
            return
        apply_camera_toggle(token_index, enable, voice_manager)
        _write_voice_state()

    async def _dashboard_leave(self, command):
        token_index = command.get("token_index")
        channel_id = command.get("channel_id")
        if not isinstance(token_index, int) or not isinstance(channel_id, str):
            return

        tokens = self.bot.config.get("voice_token", [])
        if token_index < 0 or token_index >= len(tokens):
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            return

        if _audio_owner(token_index):
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.disconnect_voice(token_index)
            except Exception:
                ok = False
            if not ok:
                logger.warning(
                    "Voice token %s: audio leave failed",
                    _token_label(token_index),
                )
            return

        guild_id, status = await _resolve_channel(
            token, channel_id, _identity_for_index(token_index)
        )
        if status == 200 and guild_id:
            voice_manager.leave_channel(token_index, str(guild_id))

    @commands.command(name="leave", aliases=["lv"])
    async def leave_channel(self, ctx, channel_id: str, token_index: int = 0):
        """{prefix}leave <channel_id> [token_index] — Leave voice channel."""
        if token_index not in range(10):
            await ctx.send("❌ Token index must be 0-9")
            return
        if _audio_owner(token_index):
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.disconnect_voice(token_index)
            except Exception:
                ok = False
            if ok:
                await ctx.send(
                    f"✅ Token {_token_label(token_index)}: left voice (audio queue kept)"
                )
            else:
                await ctx.send(
                    f"❌ Token {_token_label(token_index)}: could not leave the audio session"
                )
            return
        if not voice_manager.is_gateway_ready(token_index):
            await ctx.send(f"❌ Token {_token_label(token_index)} is not ready")
            return
        tokens = self.bot.config.get("voice_token", [])
        if token_index >= len(tokens):
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        if not channel_id.isdigit():
            return await ctx.send("❌ Channel ID must be numeric.", delete_after=8)
        try:
            guild_id, status = await _resolve_channel(
                token, channel_id, _identity_for_index(token_index)
            )
            if status == 200 and guild_id:
                voice_manager.leave_channel(token_index, str(guild_id))
                await ctx.send(f"✅ Token {_token_label(token_index)}: Left channel {channel_id}")
            elif status == 200:
                await ctx.send(f"❌ Channel {channel_id} does not belong to a guild (DM/group?).", delete_after=8)
            else:
                await ctx.send(f"❌ Channel {channel_id}: not found (HTTP {status})", delete_after=8)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", delete_after=8)

    @commands.command(name="soundboard", aliases=["sb"])
    async def play_sound(self, ctx, sound_id: str, token_index: int = 0):
        """{prefix}soundboard <sound_id> [token_index] — Play a soundboard sound in the token's current voice channel."""
        if token_index not in range(10):
            await ctx.send("❌ Token index must be 0-9")
            return
        tokens = self.bot.config.get("voice_token", [])
        if token_index >= len(tokens):
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        if not sound_id.isdigit():
            return await ctx.send("❌ Sound ID must be numeric.", delete_after=8)

        label = _token_label(token_index)
        state = build_voice_state(voice_manager, len(tokens))
        entry = next(
            (item for item in state.get("tokens", []) if item.get("index") == token_index),
            {},
        )
        channels = entry.get("channels") or []
        if not channels:
            await ctx.send(f"❌ Token {label} is not in a voice channel.")
            return
        if len(channels) > 1:
            await ctx.send(f"❌ Token {label} is in multiple voice channels — leave one first.")
            return
        channel_id = channels[0]

        payload = {"sound_id": str(sound_id)}

        status, data = await api_request(
            "POST", f"{API_BASE}/channels/{channel_id}/send-soundboard-sound",
            token=token, json_body=payload,
            session_identity=_identity_for_index(token_index),
        )
        if status == 204:
            return await ctx.send("✅ Sound sent!")
        if status is None:
            return await ctx.send("❌ Could not reach the Discord API (network error).", delete_after=10)
        err = data.get("message") if isinstance(data, dict) else None
        await ctx.send(f"❌ Error {status}: {err or 'unknown'}", delete_after=10)

    @commands.command(name="sb_list")
    async def list_soundboard(self, ctx, guild_id: str, token_index: int = 0):
        """{prefix}sb_list <guild_id> [token_index] — List the server's soundboard sounds."""
        if not guild_id.isdigit():
            return await ctx.send("❌ Guild ID must be numeric.", delete_after=8)
        tokens = self.bot.config.get("voice_token", [])
        if token_index not in range(len(tokens)):
            return await ctx.send(f"❌ Token {_token_label(token_index)} not configured", delete_after=8)
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            return await ctx.send(f"❌ Token {_token_label(token_index)} not configured", delete_after=8)
        status, data = await api_request(
            "GET",
            f"{API_BASE}/guilds/{guild_id}/soundboard-sounds",
            token=token,
            session_identity=_identity_for_index(token_index),
        )
        if status != 200 or not isinstance(data, dict):
            return await ctx.send(f"❌ Could not fetch soundboard sounds (HTTP {status}).", delete_after=8)
        items = data.get("items") or []
        if not items:
            return await ctx.send("❌ Server has no soundboard sounds.", delete_after=8)
        lines = [f"• `{s.get('sound_id')}` — {s.get('name')} {_sound_emoji(s)}" for s in items[:25]]
        if len(items) > 25:
            lines.append(f"… and {len(items) - 25} more sounds")
        await ctx.send("**🎵 SOUNDBOARD SOUNDS**\n" + "\n".join(lines), delete_after=30)

    @commands.command(name="play")
    async def play_audio(self, ctx, token_index: int, *, query: str):
        """{prefix}play <token_index> <YouTube link or search query> — Queue audio in the token's current voice channel."""
        if token_index not in range(10):
            await ctx.send("❌ Token index must be 0-9")
            return
        tokens = self.bot.config.get("voice_token", [])
        if token_index >= len(tokens):
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return

        query = query.strip()
        if not 1 <= len(query) <= 300:
            await ctx.send("❌ Query must be 1-300 characters.")
            return

        label = _token_label(token_index)
        state = build_voice_state(voice_manager, len(tokens))
        entry = next(
            (item for item in state.get("tokens", []) if item.get("index") == token_index),
            {},
        )
        channels = entry.get("channels") or []
        if not channels:
            await ctx.send(f"❌ Token {label} is not in a voice channel — use .join first.")
            return
        if len(channels) > 1:
            await ctx.send(f"❌ Token {label} is in multiple voice channels — leave one first.")
            return
        channel_id = channels[0]
        guild_id = entry.get("guild_id") or ""

        try:
            from src.voice_audio import audio_streamer
        except Exception:
            await ctx.send("❌ Audio module is unavailable.")
            return

        try:
            result = await audio_streamer.play(token_index, guild_id, channel_id, query)
        except RuntimeError as exc:
            message = str(exc)
            if "is not active" in message or "is not connected" in message:
                await ctx.send(f"❌ Token {label} audio client is not active.")
            else:
                await ctx.send(f"❌ Could not play audio: {message}")
            return
        except Exception:
            await ctx.send("❌ Could not play audio.")
            return

        title = result.get("title") if isinstance(result, dict) else query
        position = result.get("position") if isinstance(result, dict) else "?"
        await ctx.send(f"✅ Queued: **{title}** (position {position})")

    @commands.command(name="join", aliases=["jv"])
    async def join_channel(self, ctx, channel_ids: str, token_index: int = 0):
        """{prefix}join <id1,id2> [token_index] — Join voice channel(s). Max 2 channels.

All channels share the token's gateway session (one voice state per guild).
Two channels in the same guild: the last one wins (Discord limit).

Examples:
  {prefix}join 123456789
  {prefix}join 123456789,987654321 0
  {prefix}join 123456789 2
        """
        if token_index not in range(10):
            await ctx.send("❌ Token index must be 0-9")
            return
        if _audio_owner(token_index):
            requested = [
                cid.strip() for cid in channel_ids.split(",") if cid.strip()
            ]
            target = next((cid for cid in requested if cid.isdigit()), None)
            if target is None:
                await ctx.send("❌ Provide at least 1 numeric channel ID")
                return
            try:
                from src.voice_audio import audio_streamer

                ok = await audio_streamer.move_to(token_index, target)
            except Exception:
                ok = False
            if ok:
                await ctx.send(
                    f"✅ Token {_token_label(token_index)}: moved the audio session to channel {target}"
                )
            else:
                await ctx.send(
                    f"❌ Token {_token_label(token_index)}: could not move the audio session to channel {target}"
                )
            return
        if not voice_manager.is_gateway_ready(token_index):
            await ctx.send(f"❌ Token {_token_label(token_index)} is not ready")
            tokens = self.bot.config.get("voice_token", [])
            if token_index >= len(tokens):
                await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
                return
            token = tokens[token_index]
            if not isinstance(token, str) or not token.strip():
                await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
                return
            # Same identity probe as the boot path: never open a duplicate
            # main-account session just because the join raced READY.
            await self._boot_index(token_index, token)
            # Poll tối đa 15s (3×5s) — mạng chậm vẫn kịp READY
            for _ in range(3):
                await asyncio.sleep(5)
                if voice_manager.is_gateway_ready(token_index):
                    break
            if not voice_manager.is_gateway_ready(token_index):
                await ctx.send(f"❌ Token {_token_label(token_index)} still not ready. Check token.")
                return

        channels = [cid.strip() for cid in channel_ids.split(",") if cid.strip()]
        if not channels:
            await ctx.send("❌ Provide at least 1 channel ID")
            return
        if len(channels) > 2:
            await ctx.send("❌ Maximum 2 channels per command")
            return

        tokens = self.bot.config.get("voice_token", [])
        if token_index >= len(tokens):
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            await ctx.send(f"❌ Token {_token_label(token_index)} not configured")
            return

        # Resolve channels → get guild_id
        resolved = []
        try:
            for ch_id in channels:
                if not ch_id.isdigit():
                    await ctx.send(f"❌ Channel {ch_id}: ID must be numeric", delete_after=8)
                    continue
                guild_id, status = await _resolve_channel(
                    token, ch_id, _identity_for_index(token_index)
                )
                if status == 200 and guild_id:
                    resolved.append((str(guild_id), ch_id))
                elif status == 200:
                    await ctx.send(f"❌ Channel {ch_id} does not belong to a guild (DM/group?) — skipped", delete_after=8)
                else:
                    await ctx.send(f"❌ Channel {ch_id}: HTTP {status}", delete_after=8)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", delete_after=8)
            return

        if not resolved:
            await ctx.send("❌ No valid channels")
            return

        record_manual = None
        try:
            from src.voice_actions.autoroom import (
                clear_expected,
                expect_move,
                get_auto_room_config,
                mark_manual,
            )

            auto_room = get_auto_room_config()
            auto_guild = str(auto_room.get("guild_id") or "")
            auto_enabled = bool(auto_room.get("enabled"))

            def record_manual(guild_id, channel_id, joined):
                if not joined:
                    clear_expected(token_index, guild_id)
                    return
                if auto_enabled and guild_id == auto_guild:
                    mark_manual(token_index, guild_id, channel_id)
                    clear_expected(token_index, guild_id)

            for guild_id, channel_id in resolved:
                expect_move(token_index, guild_id, channel_id)
        except Exception:
            logger.debug(
                "Auto-room move expectation not recorded", exc_info=True
            )

        # Single channel → stable mode
        if len(resolved) == 1:
            guild_id, ch_id = resolved[0]
            gateway = voice_manager.join_channel_single(
                index=token_index,
                guild_id=guild_id,
                channel_id=ch_id,
                on_voice_connected=_on_voice_connected,
                on_voice_disconnected=_on_voice_disconnected,
                token=token,
            )
            if record_manual is not None:
                record_manual(guild_id, ch_id, gateway is not None)
            if gateway is None:
                await ctx.send(
                    f"❌ Token {_token_label(token_index)}: could not join channel {ch_id}"
                )
            else:
                await ctx.send(f"✅ Token {_token_label(token_index)}: Joined guild {guild_id} ch={ch_id} (stable)")

        # Multiple channels → multi mode
        else:
            guild_ids = [g for g, _ in resolved]
            if len(set(guild_ids)) < len(guild_ids):
                await ctx.send(
                    "⚠️ Two channels are in the same server — Discord allows only one voice channel per user per guild. "
                    "The token will stay in the last channel.",
                    delete_after=10,
                )
            await ctx.send(f"⏳ Token {_token_label(token_index)}: Joining {len(resolved)} channel(s)...")
            joined = 0
            for guild_id, ch_id in resolved:
                connector = voice_manager.join_channel_multi(
                    index=token_index,
                    token=token,
                    guild_id=guild_id,
                    channel_id=ch_id,
                    on_voice_connected=_on_voice_connected,
                    on_voice_disconnected=_on_voice_disconnected,
                )
                if record_manual is not None:
                    record_manual(guild_id, ch_id, connector is not None)
                if connector is None:
                    await ctx.send(
                        f"❌ Token {_token_label(token_index)}: could not join channel {ch_id}",
                        delete_after=8,
                    )
                else:
                    joined += 1
                await asyncio.sleep(2)
            if joined:
                await ctx.send(
                    f"✅ Done — {joined}/{len(resolved)} channel(s) joined (multi)"
                )


async def setup(bot):
    await bot.add_cog(Voice(bot))
