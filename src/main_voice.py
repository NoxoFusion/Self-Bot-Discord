"""Route the main account's voice state through the bot's own gateway session.

Opening a second gateway session for the same token makes Discord invalidate
the first one (and can force a password reset).  :class:`MainVoiceBridge`
implements the small ``VoiceConnector`` surface used by
:class:`src.voice_connector.VoiceManager` on top of the already-connected bot,
so the main token can still join voice without a duplicate WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MainVoiceBridge:
    """VoiceConnector-compatible adapter around the main ``commands.Bot``."""

    def __init__(self, bot: Any, index: int):
        self.bot = bot
        self.index = int(index)
        # guild_id -> channel_id, same shape as VoiceConnector.
        self.voice_channels: dict[str, str] = {}
        # Guilds confirmed by a VOICE_STATE_UPDATE dispatch.
        self._confirmed_channels: dict[str, str] = {}
        self.self_mute = True
        self.self_deaf = False
        self.is_streaming = False
        self.is_video = False
        self.gateway_only = False
        self._callbacks = {
            "on_ready": None,
            "on_voice_connected": None,
            "on_voice_disconnected": None,
            "on_voice_moved": None,
        }

    # ------------------------------------------------------------------
    # Connector-compatible properties
    # ------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        checker = getattr(self.bot, "is_ready", None)
        try:
            return bool(checker()) if callable(checker) else bool(checker)
        except Exception:
            return False

    @property
    def voice_connected(self) -> bool:
        return bool(self.voice_channels)

    @property
    def user_id(self) -> str | None:
        user = getattr(self.bot, "user", None)
        user_id = getattr(user, "id", None)
        return str(user_id) if user_id is not None else None

    @property
    def username(self) -> str | None:
        user = getattr(self.bot, "user", None)
        return getattr(user, "name", None) if user is not None else None

    def _primary(self) -> tuple[str | None, str | None]:
        if not self.voice_channels:
            return None, None
        guild_id = next(reversed(self.voice_channels))
        return guild_id, self.voice_channels[guild_id]

    @property
    def guild_id(self) -> str | None:
        return self._primary()[0]

    @property
    def channel_id(self) -> str | None:
        return self._primary()[1]

    @property
    def guild_channels(self) -> dict[str, list[dict[str, Any]]]:
        """Read-only voice/stage channel snapshot for the dashboard picker."""

        guilds = list(getattr(self.bot, "guilds", None) or [])
        if not guilds:
            guilds = [
                self._get_guild(guild_id)
                for guild_id in list(self.voice_channels)
            ]

        snapshot: dict[str, list[dict[str, Any]]] = {}
        for guild in guilds:
            if guild is None:
                continue
            guild_id = getattr(guild, "id", None)
            if guild_id is None:
                continue
            channels: list[dict[str, Any]] = []
            for channel in (
                list(getattr(guild, "voice_channels", None) or [])
                + list(getattr(guild, "stage_channels", None) or [])
            ):
                channel_id = getattr(channel, "id", None)
                if channel_id is None:
                    continue
                channels.append(
                    {
                        "id": str(channel_id),
                        "name": getattr(channel, "name", ""),
                        "position": getattr(channel, "position", 0),
                    }
                )
            snapshot[str(guild_id)] = channels
        return snapshot

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def _get_guild(self, guild_id: Any) -> Any | None:
        getter = getattr(self.bot, "get_guild", None)
        if not callable(getter):
            return None
        try:
            return getter(int(guild_id))
        except (TypeError, ValueError):
            return None
        except Exception:
            logger.debug(
                "Main voice #%s: get_guild(%r) failed",
                self.index,
                guild_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def _get_channel(guild: Any, channel_id: Any) -> Any | None:
        getter = getattr(guild, "get_channel", None)
        if not callable(getter):
            return None
        try:
            return getter(int(channel_id))
        except (TypeError, ValueError):
            return None
        except Exception:
            return None

    def _channel_for(self, guild_id: Any = None) -> tuple[str | None, str | None]:
        """Return ``(guild_id, channel_id)`` for one entry, like the connector."""

        guild = str(guild_id) if guild_id else self.guild_id
        if not guild:
            return None, None
        channel = self.voice_channels.get(guild)
        if channel is None and guild == self.guild_id:
            channel = self.channel_id
        return guild, channel

    def _stream_key(self, guild_id: Any = None) -> str | None:
        """Stream key used by op 18/19/22 — ``None`` without voice context."""

        guild, channel = self._channel_for(guild_id)
        if not guild or not channel or not self.user_id:
            return None
        return f"guild:{guild}:{channel}:{self.user_id}"

    # ------------------------------------------------------------------
    # Async scheduling
    # ------------------------------------------------------------------
    def _schedule(self, coroutine: Any, description: str) -> asyncio.Task | None:
        """Schedule ``coroutine`` on the running loop; never raise to callers."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "Main voice #%s: no running event loop for %s",
                self.index,
                description,
            )
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            return None

        try:
            task = loop.create_task(coroutine)
        except Exception:
            logger.exception(
                "Main voice #%s: could not schedule %s", self.index, description
            )
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            return None

        task.add_done_callback(self._log_task_result)
        return task

    def _log_task_result(self, task: asyncio.Task) -> None:
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Main voice #%s: task inspection failed", self.index)
            return
        if error is not None:
            logger.error(
                "Main voice #%s: scheduled task failed: %s",
                self.index,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _change_voice_state(
        self,
        guild_id: str,
        channel_id: str | None,
        self_mute: bool,
        self_deaf: bool,
        self_video: bool,
    ) -> None:
        guild = self._get_guild(guild_id)
        if guild is None:
            logger.warning(
                "Main voice #%s: guild %s is not available", self.index, guild_id
            )
            return

        channel = None
        if channel_id is not None:
            channel = self._get_channel(guild, channel_id)
            if channel is None:
                logger.warning(
                    "Main voice #%s: channel %s is not available in guild %s",
                    self.index,
                    channel_id,
                    guild_id,
                )
                return

        changer = getattr(guild, "change_voice_state", None)
        if not callable(changer):
            logger.warning(
                "Main voice #%s: guild %s has no change_voice_state",
                self.index,
                guild_id,
            )
            return

        try:
            await changer(
                channel=channel,
                self_mute=bool(self_mute),
                self_deaf=bool(self_deaf),
                self_video=bool(self_video),
            )
        except Exception:
            logger.exception(
                "Main voice #%s: change_voice_state failed for guild %s",
                self.index,
                guild_id,
            )

    async def _send_payloads(self, payloads: list[dict[str, Any]]) -> None:
        ws = getattr(self.bot, "ws", None)
        sender = getattr(ws, "send_as_json", None)
        if not callable(sender):
            logger.warning(
                "Main voice #%s: gateway websocket is not available", self.index
            )
            return
        for payload in payloads:
            try:
                await sender(payload)
            except Exception:
                logger.exception(
                    "Main voice #%s: gateway payload op %s failed",
                    self.index,
                    payload.get("op"),
                )
                return

    def _fire(self, name: str, *args: Any) -> None:
        callback = self._callbacks.get(name)
        if not callable(callback):
            return
        try:
            callback(*args)
        except Exception:
            logger.exception(
                "Main voice #%s: %s callback failed", self.index, name
            )

    # ------------------------------------------------------------------
    # Connector-compatible lifecycle / voice methods
    # ------------------------------------------------------------------
    def start(self) -> None:
        """The main bot is already connected; nothing to boot."""

    def stop(self) -> None:
        """Leave every guild held by this bridge."""

        self.leave_voice()

    def join_voice(self, guild_id: Any = None, channel_id: Any = None) -> bool:
        """Join/move the main account through its own gateway session."""

        guild = str(guild_id) if guild_id else self.guild_id
        channel = str(channel_id) if channel_id else self.voice_channels.get(guild)
        if channel is None and guild == self.guild_id:
            channel = self.channel_id
        if not guild or not channel:
            return False

        self.voice_channels[guild] = channel
        if self._confirmed_channels.get(guild) != channel:
            self._confirmed_channels.pop(guild, None)
        self._schedule(
            self._change_voice_state(
                guild, channel, self.self_mute, self.self_deaf, self.is_video
            ),
            f"join {guild}/{channel}",
        )
        return True

    def leave_voice(self, guild_id: Any = None) -> bool:
        """Leave one guild (or every guild in the map)."""

        if guild_id is not None:
            guilds = [str(guild_id)]
        elif self.voice_channels:
            guilds = list(self.voice_channels)
        else:
            guilds = []

        was_streaming = self.is_streaming
        for guild in guilds:
            if was_streaming:
                key = self._stream_key(guild)
                if key:
                    self._schedule(
                        self._send_payloads(
                            [{"op": 19, "d": {"stream_key": key}}]
                        ),
                        f"stop stream {guild}",
                    )
            self.voice_channels.pop(guild, None)
            self._confirmed_channels.pop(guild, None)
            self._schedule(
                self._change_voice_state(guild, None, False, False, False),
                f"leave {guild}",
            )

        self.is_streaming = False
        return bool(guilds)

    def update_voice_state(
        self,
        guild_id: Any = None,
        channel_id: Any = None,
        self_mute: bool | None = None,
        self_deaf: bool | None = None,
    ) -> bool:
        """Move or mute/deafen one guild through ``change_voice_state``."""

        guild, channel = self._channel_for(guild_id)
        if not guild:
            return False

        if channel_id is not None:
            new_channel = str(channel_id)
            if channel is None:
                return False
            if new_channel != channel:
                self.voice_channels[guild] = new_channel
                self._confirmed_channels.pop(guild, None)
                channel = new_channel

        if not channel:
            return False

        mute = self.self_mute if self_mute is None else bool(self_mute)
        deaf = self.self_deaf if self_deaf is None else bool(self_deaf)
        self._schedule(
            self._change_voice_state(
                guild, channel, mute, deaf, self.is_video
            ),
            f"update {guild}/{channel}",
        )
        self.self_mute = mute
        self.self_deaf = deaf
        return True

    def set_camera(self, enabled: bool, guild_id: Any = None) -> bool:
        """Toggle the camera flag for one guild."""

        guild, channel = self._channel_for(guild_id)
        if not guild or not channel:
            return False
        self._schedule(
            self._change_voice_state(
                guild, channel, self.self_mute, self.self_deaf, bool(enabled)
            ),
            f"camera {guild}",
        )
        self.is_video = bool(enabled)
        return True

    def start_stream(self, guild_id: Any = None) -> bool:
        """Start Go Live signaling (op 18 + op 22) for one guild."""

        guild, channel = self._channel_for(guild_id)
        key = self._stream_key(guild)
        if not guild or not channel or not key:
            return False

        self._schedule(
            self._send_payloads(
                [
                    {
                        "op": 18,
                        "d": {
                            "type": "guild",
                            "guild_id": guild,
                            "channel_id": channel,
                            "preferred_region": None,
                        },
                    },
                    {"op": 22, "d": {"stream_key": key, "paused": False}},
                ]
            ),
            f"start stream {guild}",
        )
        self.is_streaming = True
        return True

    def stop_stream(self, guild_id: Any = None) -> bool:
        """Stop Go Live signaling (op 19) for one or every guild."""

        if guild_id is not None:
            guilds = [str(guild_id)]
        elif self.voice_channels:
            guilds = list(self.voice_channels)
        else:
            guilds = []

        payloads = []
        for guild in guilds:
            key = self._stream_key(guild)
            if key:
                payloads.append({"op": 19, "d": {"stream_key": key}})
        if payloads:
            self._schedule(self._send_payloads(payloads), "stop stream")
        self.is_streaming = False
        return True

    def get_voice_channels(self, guild_id: Any) -> list[dict[str, Any]]:
        """Return the cached voice/stage channels for ``guild_id``."""

        if not guild_id:
            return []
        try:
            return list(self.guild_channels.get(str(guild_id), []))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Gateway event handling (called by the Voice cog listener)
    # ------------------------------------------------------------------
    def handle_state_update(
        self,
        guild_id: Any,
        channel_id: Any,
        self_mute: bool = False,
        self_deaf: bool = False,
        self_video: bool = False,
        self_stream: bool = False,
    ) -> None:
        """Mirror one ``VOICE_STATE_UPDATE`` for the main account."""

        if guild_id is None:
            return

        guild = str(guild_id)
        channel = str(channel_id) if channel_id is not None else None

        self.self_mute = bool(self_mute)
        self.self_deaf = bool(self_deaf)
        self.is_video = bool(self_video)
        self.is_streaming = bool(self_stream)

        if channel is None:
            if guild in self.voice_channels or guild in self._confirmed_channels:
                old_channel = (
                    self.voice_channels.get(guild)
                    or self._confirmed_channels.get(guild)
                )
                self.voice_channels.pop(guild, None)
                self._confirmed_channels.pop(guild, None)
                self._fire(
                    "on_voice_disconnected", self.index, guild, old_channel
                )
            return

        old_channel = self._confirmed_channels.get(guild)
        newly_confirmed = guild not in self._confirmed_channels
        self.voice_channels[guild] = channel
        self._confirmed_channels[guild] = channel

        if newly_confirmed:
            self._fire("on_voice_connected", self.index, guild, channel)
        elif old_channel and old_channel != channel:
            self._fire(
                "on_voice_moved", self.index, guild, old_channel, channel
            )
