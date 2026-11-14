"""
Voice Connector — một gateway WebSocket giữ nhiều guild voice state.
Mọi join/leave đi qua map guild_id -> channel_id trên gateway connector.
Hoàn toàn im lặng — không log (trừ cảnh báo dedupe cùng guild).
"""

import json
import logging
import time
import threading
from types import SimpleNamespace

import websocket

from .client_identity import (
    client_properties,
    session_identity as make_session_identity,
)
from .retry_policy import AUTH_CLOSE_CODES

logger_ws = logging.getLogger(__name__)

GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"


class VoiceConnector(threading.Thread):
    """Gateway WebSocket — giữ voice state của nhiều guild qua voice_channels."""

    def __init__(self, token, guild_id, channel_id, index,
                 on_ready=None, on_voice_connected=None, on_voice_disconnected=None,
                 on_voice_moved=None, on_token_dead=None, telemetry_enabled=False,
                 session_identity=None, gateway_only=False):
        super().__init__(daemon=True)
        self.token = token
        self.guild_id = str(guild_id) if guild_id else None
        self.channel_id = str(channel_id) if channel_id else None
        # guild_id -> channel_id — một gateway session giữ nhiều guild voice state.
        self.voice_channels = {}
        if self.guild_id and self.channel_id:
            self.voice_channels[self.guild_id] = self.channel_id
        # guild -> channel đã được Discord xác nhận qua VOICE_STATE_UPDATE.
        self._confirmed_channels = {}
        self.index = index
        self.ws = None
        self.connected = False
        # Backward-compatible: connected khi map có ít nhất 1 guild.
        self.voice_connected = bool(self.voice_channels)
        self.user_id = None
        self.username = None
        self.analytics_token = None
        self.session_id = None
        self.telemetry = None
        self.connected_at = None
        self.gateway_only = gateway_only
        self.is_streaming = False
        self.is_video = False
        self.self_mute = True
        self.self_deaf = False
        # guild_id -> [{id, name, position}] cho voice/stage channels.
        self.guild_channels = {}
        self._ready_event = threading.Event()
        self._should_stop = False
        self._heartbeat_thread = None
        self._hb_stop = threading.Event()
        self._callbacks = {
            "on_ready": on_ready,
            "on_voice_connected": on_voice_connected,
            "on_voice_disconnected": on_voice_disconnected,
            "on_voice_moved": on_voice_moved,
            "on_token_dead": on_token_dead,
        }
        # Per-session identifiers: every connector is its own "browser
        # instance" so accounts never share launch ids/signatures.
        self.session_identity = session_identity or make_session_identity()
        self.telemetry_enabled = bool(telemetry_enabled)
        self._dead_reported = False

    def _sync_primary(self):
        """Đồng bộ attribute cũ (guild_id/channel_id/voice_connected) từ map.

        guild_id/channel_id = entry cuối cùng (primary); voice_connected = map khác rỗng.
        """
        if self.voice_channels:
            self.guild_id, self.channel_id = next(reversed(self.voice_channels.items()))
        else:
            self.guild_id = None
            self.channel_id = None
        self.voice_connected = bool(self.voice_channels)

    def run(self):
        while not self._should_stop:
            try:
                self.connected = False
                self.voice_connected = bool(self.voice_channels)
                self._confirmed_channels.clear()
                self._ready_event.clear()
                self.ws = websocket.WebSocketApp(
                    GATEWAY_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever()
            except Exception:
                pass
            if self._should_stop:
                break
            self.connected = False
            self.voice_connected = bool(self.voice_channels)
            self._confirmed_channels.clear()
            time.sleep(30)  # Reconnect sau 30s

    def send_json(self, payload):
        try:
            if self.ws and self.ws.sock and self.ws.sock.connected:
                self.ws.send(json.dumps(payload))
        except Exception:
            pass

    def _on_open(self, ws):
        auth_payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "capabilities": 16381,
                "properties": client_properties(self.session_identity),
                "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                "compress": False,
                "client_state": {
                    "guild_hashes": {},
                    "highest_last_message_id": "0",
                    "read_state_version": 0,
                    "user_guild_settings_version": -1,
                    "user_settings_version": -1,
                },
            },
        }
        self.send_json(auth_payload)

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            op = data.get("op")
            t = data.get("t")

            if op == 10:
                interval = data["d"]["heartbeat_interval"] / 1000
                # Đánh thức heartbeat cũ thoát NGAY qua Event (không join-chờ cả interval nữa)
                if self._hb_stop:
                    self._hb_stop.set()
                self._hb_stop = threading.Event()
                self.connected = True
                self._heartbeat_thread = threading.Thread(target=self._heartbeat, args=(interval, self._hb_stop), daemon=True)
                self._heartbeat_thread.start()

            elif t == "READY":
                self.user_id = str(data["d"]["user"]["id"])
                self.username = data["d"]["user"].get("username", "Unknown")
                self.analytics_token = data["d"].get("analytics_token")
                self.session_id = data["d"].get("session_id")
                self.connected = True
                self.connected_at = time.time()
                self._ready_event.set()

                if self.telemetry_enabled and self.analytics_token and not self.telemetry:
                    # Telemetry chạy trong thread RIÊNG — không block thread WS
                    # (block ở đây = mất heartbeat = Discord ngắt kết nối)
                    def _start_telemetry():
                        try:
                            from src.telemetry import TelemetrySender
                            t = TelemetrySender(
                                self.token,
                                self.user_id,
                                session_identity=self.session_identity,
                            )
                            t.analytics_token = self.analytics_token
                            # Gán NGAY trước các bước dài — guard `not self.telemetry`
                            # chặn luôn instance thứ hai nếu gateway reconnect nhanh
                            self.telemetry = t
                            import asyncio
                            loop = asyncio.new_event_loop()
                            loop.run_until_complete(t.send_initial_events())
                            loop.close()
                            t.start_periodic(300)
                        except Exception:
                            pass
                    threading.Thread(target=_start_telemetry, daemon=True, name=f"tel-{self.index}").start()

                cb = self._callbacks.get("on_ready")
                if cb:
                    try:
                        cb(self.index, self.user_id, self.username)
                    except Exception:
                        pass

                # Reconnect: giữ nguyên map và rejoin TẤT CẢ guild sau khi READY.
                self._confirmed_channels.clear()
                if not self.gateway_only and self.voice_channels:
                    entries = list(self.voice_channels.items())

                    def _rejoin_all():
                        for gid, cid in entries:
                            self.join_voice(gid, cid)

                    threading.Timer(2.0, _rejoin_all).start()

            elif t == "GUILD_CREATE":
                # Cache voice/stage channels so the dashboard can offer a
                # channel picker without any REST call. Never let a malformed
                # dispatch kill the WebSocket thread.
                try:
                    guild = data.get("d") or {}
                    guild_id = guild.get("id")
                    raw_channels = guild.get("channels")
                    if guild_id and isinstance(raw_channels, list):
                        channels = []
                        for channel in raw_channels:
                            if not isinstance(channel, dict):
                                continue
                            if channel.get("type") not in (2, 13):
                                continue
                            channel_id = channel.get("id")
                            if not channel_id:
                                continue
                            channels.append(
                                {
                                    "id": str(channel_id),
                                    "name": channel.get("name"),
                                    "position": channel.get("position", 0),
                                }
                            )
                        self.guild_channels[str(guild_id)] = channels
                except Exception:
                    pass

            elif t == "VOICE_STATE_UPDATE":
                d = data["d"]
                if str(d.get("user_id")) == self.user_id:
                    guild_id = str(d["guild_id"]) if d.get("guild_id") else None
                    # Mỗi session chỉ theo dõi guild nó sở hữu — tránh session phụ
                    # nhận VOICE_STATE_UPDATE của session khác rồi ghi đè map.
                    owned = set(self.voice_channels)
                    if self.guild_id:
                        owned.add(str(self.guild_id))
                    if guild_id and guild_id in owned:
                        ch = d.get("channel_id")  # None khi rời kênh — so null thật
                        if ch is None:
                            # Chỉ xoá đúng guild này; các guild khác trong map giữ nguyên.
                            if (guild_id in self.voice_channels
                                    or guild_id in self._confirmed_channels):
                                old_channel = (self.voice_channels.get(guild_id)
                                               or self._confirmed_channels.get(guild_id))
                                self.voice_channels.pop(guild_id, None)
                                self._confirmed_channels.pop(guild_id, None)
                                self._sync_primary()
                                cb = self._callbacks.get("on_voice_disconnected")
                                if cb:
                                    try:
                                        cb(self.index, guild_id, old_channel)
                                    except Exception:
                                        pass
                        else:
                            ch = str(ch)
                            old = self._confirmed_channels.get(guild_id)
                            newly_confirmed = guild_id not in self._confirmed_channels
                            self.voice_channels[guild_id] = ch
                            self._confirmed_channels[guild_id] = ch
                            self._sync_primary()
                            if newly_confirmed:
                                cb = self._callbacks.get("on_voice_connected")
                                if cb:
                                    try:
                                        cb(self.index, guild_id, ch)
                                    except Exception:
                                        pass
                            elif old and old != ch:
                                cb = self._callbacks.get("on_voice_moved")
                                if cb:
                                    try:
                                        cb(self.index, guild_id, old, ch)
                                    except Exception:
                                        pass
                        # Đồng bộ cờ stream/camera từ dispatch của chính user (stream bị
                        # Discord/kick kết thúc → UI phản ánh đúng thực tế)
                        if "self_stream" in d:
                            self.is_streaming = bool(d["self_stream"])
                        if "self_video" in d:
                            self.is_video = bool(d["self_video"])

        except Exception:
            pass

    def _heartbeat(self, interval, stop_event):
        import random as _random
        # Discord khuyến nghị beat đầu sau interval * random(0,1) — tránh bị close 4008/4009
        first_jitter = interval * _random.random()
        if stop_event.wait(first_jitter):
            return
        while not self._should_stop:
            if not self.connected:
                break
            try:
                self.send_json({"op": 1, "d": None})
            except Exception:
                break
            # wait() trả True ngay khi Event được set → thoát tức thì (thay sleep ~41s)
            if stop_event.wait(interval):
                break

    def _on_error(self, ws, error):
        pass

    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.voice_connected = bool(self.voice_channels)
        self._confirmed_channels.clear()
        # Close code auth/session không thể tự phục hồi — dừng reconnect.
        # Báo cho cog để evict token khỏi pool.
        if close_status_code in AUTH_CLOSE_CODES:
            uptime = None
            if self.connected_at is not None:
                uptime = max(0.0, time.time() - self.connected_at)
            logger_ws.error(
                "Gateway đóng %s (%s) sau %s — dừng reconnect token #%s",
                close_status_code,
                close_msg or "no reason",
                f"{uptime:.1f}s" if uptime is not None else "?",
                self.index,
            )
            if uptime is not None and uptime < 2.0:
                logger_ws.warning(
                    "⚠️ Token #%s bị kill ngay sau READY (%.1fs, code %s) — "
                    "khả năng cao ACCOUNT BỊ FLAG ở cấp Discord, không phải "
                    "lỗi code. Hãy thử một account mới.",
                    self.index,
                    uptime,
                    close_status_code,
                )
            self._should_stop = True
            if not self._dead_reported:
                self._dead_reported = True
                cb = self._callbacks.get("on_token_dead")
                if cb:
                    try:
                        cb(self.index, close_status_code)
                    except Exception:
                        pass

        # Các close code khác (1006 abnormal, timeout, etc.) → KHÔNG set _should_stop
        # → reconnect loop ở line 50-69 chạy lại sau 30s sleep

    def _channel_for(self, guild_id=None):
        """Trả (guild_id, channel_id) của entry tương ứng — fallback attribute cũ."""
        guild = str(guild_id) if guild_id else self.guild_id
        if not guild:
            return None, None
        channel = self.voice_channels.get(guild)
        if channel is None and guild == self.guild_id:
            channel = self.channel_id
        return guild, channel

    def _stream_key(self, guild_id=None):
        """Stream key Discord dùng cho op 18/19/22 — None khi thiếu voice context."""
        guild, channel = self._channel_for(guild_id)
        if not guild or not channel or not self.user_id:
            return None
        return f"guild:{guild}:{channel}:{self.user_id}"

    def start_stream(self, guild_id=None):
        """Bật Go Live (signaling-only) cho 1 guild: tạo stream rồi unpause."""
        guild, channel = self._channel_for(guild_id)
        key = self._stream_key(guild)
        if not guild or not channel or not key:
            return False
        self.send_json({
            "op": 18,
            "d": {
                "type": "guild",
                "guild_id": guild,
                "channel_id": channel,
                "preferred_region": None,
            },
        })
        self.send_json({"op": 22, "d": {"stream_key": key, "paused": False}})
        self.is_streaming = True
        return True

    def stop_stream(self, guild_id=None):
        """Tắt Go Live — gửi op 19 cho guild chỉ định (hoặc mọi guild trong map)."""
        if guild_id is not None:
            guilds = [str(guild_id)]
        elif self.voice_channels:
            guilds = list(self.voice_channels)
        elif self.guild_id:
            guilds = [self.guild_id]
        else:
            guilds = []
        for guild in guilds:
            key = self._stream_key(guild)
            if key:
                self.send_json({"op": 19, "d": {"stream_key": key}})
        self.is_streaming = False
        return True

    def set_camera(self, enabled, guild_id=None):
        """Bật/tắt camera qua self_video trong op 4 cho 1 guild."""
        guild, channel = self._channel_for(guild_id)
        if not guild or not channel:
            return False
        self.send_json({
            "op": 4,
            "d": {
                "guild_id": guild,
                "channel_id": channel,
                "self_mute": self.self_mute,
                "self_deaf": self.self_deaf,
                "self_video": bool(enabled),
            },
        })
        self.is_video = bool(enabled)
        return True

    def join_voice(self, guild_id=None, channel_id=None):
        """Gửi opcode 4 để join voice channel của 1 guild; lưu vào map."""
        guild = str(guild_id) if guild_id else self.guild_id
        channel = str(channel_id) if channel_id else self.voice_channels.get(guild)
        if channel is None and guild == self.guild_id:
            channel = self.channel_id
        if not guild or not channel:
            return
        self.voice_channels[guild] = channel
        # Channel mới chưa được Discord xác nhận → lần dispatch tới sẽ fire callback.
        if self._confirmed_channels.get(guild) != channel:
            self._confirmed_channels.pop(guild, None)
        self._sync_primary()
        payload = {
            "op": 4,
            "d": {
                "guild_id": guild,
                "channel_id": channel,
                "self_mute": self.self_mute,
                "self_deaf": self.self_deaf,
                "self_video": self.is_video,
            },
        }
        self.send_json(payload)

    def update_voice_state(self, guild_id=None, channel_id=None,
                           self_mute=None, self_deaf=None):
        """Đổi mute/deafen hoặc chuyển kênh của 1 guild qua opcode 4."""
        guild, channel = self._channel_for(guild_id)
        if not guild:
            return False

        if channel_id is not None:
            new_channel = str(channel_id)
            # Chỉ move khi connector đang giữ guild này — tránh một session
            # khác trong cùng token join trùng guild (multi-mode).
            if channel is None:
                return False
            if new_channel != channel:
                self.voice_channels[guild] = new_channel
                self._confirmed_channels.pop(guild, None)
                self._sync_primary()
                channel = new_channel

        if not channel:
            return False

        mute = self.self_mute if self_mute is None else bool(self_mute)
        deaf = self.self_deaf if self_deaf is None else bool(self_deaf)
        self.send_json({
            "op": 4,
            "d": {
                "guild_id": guild,
                "channel_id": channel,
                "self_mute": mute,
                "self_deaf": deaf,
                "self_video": self.is_video,
            },
        })
        self.self_mute = mute
        self.self_deaf = deaf
        return True

    def get_voice_channels(self, guild_id):
        """Trả cache voice/stage channels của guild (rỗng nếu chưa có)."""
        if not guild_id:
            return []
        try:
            return list(self.guild_channels.get(str(guild_id), []))
        except Exception:
            return []

    def leave_voice(self, guild_id=None):
        """Gửi opcode 4 leave cho 1 guild (hoặc tất cả guild khi None)."""
        if guild_id is not None:
            guilds = [str(guild_id)]
        elif self.voice_channels:
            guilds = list(self.voice_channels)
        elif self.guild_id:
            guilds = [self.guild_id]
        else:
            return
        # Kết thúc stream TRƯỚC khi rời kênh — stream key vẫn còn channel_id
        was_streaming = self.is_streaming
        for guild in guilds:
            if was_streaming:
                key = self._stream_key(guild)
                if key:
                    self.send_json({"op": 19, "d": {"stream_key": key}})
            payload = {
                "op": 4,
                "d": {
                    "guild_id": guild,
                    "channel_id": None,
                    "self_mute": False,
                    "self_deaf": False,
                },
            }
            self.send_json(payload)
            self.voice_channels.pop(guild, None)
            self._confirmed_channels.pop(guild, None)
        self.is_streaming = False
        self._sync_primary()

    def stop(self):
        """Dừng WebSocket connection — không reconnect."""
        self._should_stop = True
        self.connected = False
        if self._hb_stop:
            self._hb_stop.set()
        if self.telemetry:
            self.telemetry.stop_periodic()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass


class VoiceManager:
    """Quản lý VoiceConnector instances.

    Mọi join (1 hay N kênh) đi qua map guild_id -> channel_id của gateway
    connector — 1 gateway session giữ nhiều guild voice state.
    `voice_connectors` chỉ còn là fallback cho connector cũ.
    """

    def __init__(self):
        self.gateway_connectors = {}  # index -> gateway connector (giữ voice map)
        self.voice_connectors = {}    # "index_guild_id" -> legacy voice connector
        # Indices routed through the main bot's own session (no raw gateway).
        self.main_indices: set[int] = set()
        # Main bot token.  Kept separately from ``main_indices`` because
        # ``stop_all()`` clears the indices during a dashboard reload while the
        # token itself is still the main account.
        self.main_token = None
        # Serialize boot_gateway per token index so concurrent join/reload
        # paths cannot leave an unstopped orphan gateway session behind.
        self._boot_locks: dict[int, threading.Lock] = {}
        self._boot_locks_guard = threading.Lock()
        # Defaults remembered from boot_gateway so join paths and legacy
        # connectors also evict dead tokens / honour the telemetry gate.
        self._on_token_dead = None
        self._telemetry_enabled = False
        # Auto-room installs its move callback here so tokens booted later
        # inherit it instead of silently losing auto-room handling.
        self._on_voice_moved = None

    def register_main(self, index, bridge):
        """Register the bridge that routes ``index`` through the main session."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            logger_ws.warning("Voice main bridge: invalid index %r", index)
            return bridge

        existing = self.gateway_connectors.get(index)
        if existing is not None and existing is not bridge:
            # Never leave a raw gateway session alive for the main token.
            try:
                existing.stop()
            except Exception:
                pass

        prefix = f"{index}_"
        for key in list(self.voice_connectors):
            if not key.startswith(prefix):
                continue
            legacy = self.voice_connectors.pop(key)
            try:
                legacy.stop()
            except Exception:
                pass

        self.gateway_connectors[index] = bridge
        self.main_indices.add(index)
        return bridge

    def is_main_index(self, index):
        """Return ``True`` when ``index`` uses the main bot's own session."""
        try:
            return int(index) in self.main_indices
        except (TypeError, ValueError):
            return False

    def get_main_bridge(self, index=None):
        """Return the main-session bridge for ``index`` (or the first one)."""
        if index is not None:
            try:
                index = int(index)
            except (TypeError, ValueError):
                return None
            if index not in self.main_indices:
                return None
            return self.gateway_connectors.get(index)

        for main_index in sorted(self.main_indices):
            bridge = self.gateway_connectors.get(main_index)
            if bridge is not None:
                return bridge
        return None

    def _boot_lock(self, index):
        """Return the per-index lock that serializes ``boot_gateway``."""
        with self._boot_locks_guard:
            lock = self._boot_locks.get(index)
            if lock is None:
                lock = threading.Lock()
                self._boot_locks[index] = lock
            return lock

    def _is_main_token(self, token):
        """Return ``True`` when ``token`` belongs to the main bot account."""
        main_token = self.main_token
        if not isinstance(main_token, str) or not main_token.strip():
            return False
        if not isinstance(token, str):
            return False
        return token.strip() == main_token.strip()

    def boot_gateway(self, index, token, on_ready=None, on_token_dead=None,
                     telemetry_enabled=None, on_voice_moved=None,
                     session_identity=None):
        """Boot 1 token — connect gateway only."""
        with self._boot_lock(index):
            if on_token_dead is not None:
                self._on_token_dead = on_token_dead
            if telemetry_enabled is not None:
                self._telemetry_enabled = bool(telemetry_enabled)
            if on_voice_moved is not None:
                self._on_voice_moved = on_voice_moved

            bridge = self.gateway_connectors.get(index)
            # Compare the token value too: ``stop_all()`` clears main_indices
            # during a dashboard reload, but the main token must never get a
            # second raw gateway session in that window.
            if self._is_main_token(token):
                logger_ws.warning(
                    "Voice token #%s is the main account — refusing to boot a "
                    "second gateway session",
                    index,
                )
                return bridge

            if self.is_main_index(index):
                logger_ws.warning(
                    "Voice token #%s is the main account — refusing to boot a "
                    "second gateway session",
                    index,
                )
                return bridge

            if bridge is not None:
                bridge.stop()

            connector = VoiceConnector(
                token=token,
                guild_id=None,
                channel_id=None,
                index=index,
                on_ready=on_ready,
                on_token_dead=on_token_dead or self._on_token_dead,
                telemetry_enabled=self._telemetry_enabled,
                on_voice_moved=on_voice_moved or self._on_voice_moved,
                session_identity=session_identity,
                gateway_only=True,
            )
            self.gateway_connectors[index] = connector
            connector.start()
            return connector

    def _drop_legacy(self, index, guild_id):
        """Dừng connector cũ (nếu có) để không có 2 WS cùng token/guild."""
        key = f"{index}_{guild_id}"
        legacy = self.voice_connectors.pop(key, None)
        if legacy is not None:
            try:
                legacy.leave_voice(guild_id)
            except Exception:
                pass
            try:
                legacy.stop()
            except Exception:
                pass

    def _gateway_for_join(self, index, token, guild_id,
                          on_voice_connected, on_voice_disconnected):
        """Lấy/tạo gateway connector và gắn callback; bỏ connector cũ cùng guild."""
        gw = self.gateway_connectors.get(index)
        if gw is None:
            gw = self.boot_gateway(index, token)
        if gw is None:
            return None
        gw.gateway_only = False
        gw._callbacks["on_voice_connected"] = on_voice_connected
        gw._callbacks["on_voice_disconnected"] = on_voice_disconnected
        self._drop_legacy(index, guild_id)
        return gw

    def join_channel_single(self, index, guild_id, channel_id,
                            on_voice_connected=None, on_voice_disconnected=None,
                            token=None):
        """Single mode: set map entry trên gateway connector (stable)."""
        if self.gateway_connectors.get(index) is None and not token:
            return None
        gw = self._gateway_for_join(
            index, token, guild_id,
            on_voice_connected, on_voice_disconnected,
        )
        if gw is None:
            return None
        gw.join_voice(guild_id, channel_id)
        return gw

    def join_channel_multi(self, index, token, guild_id, channel_id,
                           on_voice_connected=None, on_voice_disconnected=None):
        """Multi mode: mỗi guild 1 gateway session riêng.

        Discord chỉ cho 1 session ở 1 voice channel tại một thời điểm, nên
        muốn 1 token ở 2 kênh (2 guild) phải dùng 2 session độc lập. Gateway
        connector dùng cho single-mode được rời voice trước để tránh chiếm slot.
        """
        guild_id = str(guild_id)
        channel_id = str(channel_id)

        # Main token: never create a legacy per-guild session.  The bot's own
        # discord.py session already owns the voice state for this token.
        if self.is_main_index(index):
            bridge = self.gateway_connectors.get(index)
            if bridge is None:
                logger_ws.error(
                    "Voice main bridge #%s is not registered — refusing to "
                    "open a duplicate gateway session",
                    index,
                )
                return None
            slots = getattr(bridge, "_callbacks", None)
            if isinstance(slots, dict):
                slots["on_voice_connected"] = on_voice_connected
                slots["on_voice_disconnected"] = on_voice_disconnected
            bridge.join_voice(guild_id, channel_id)
            return bridge

        # Single-mode gateway đang ở voice → rời hết để nhường session.
        gw = self.gateway_connectors.get(index)
        if gw is not None and getattr(gw, "voice_channels", None):
            gw.leave_voice()
            gw.gateway_only = True

        key = f"{index}_{guild_id}"
        existing = self.voice_connectors.get(key)
        if existing is not None:
            if existing.connected:
                existing.guild_id = guild_id
                existing.channel_id = channel_id
                existing.voice_channels[guild_id] = channel_id
                existing._callbacks["on_voice_connected"] = on_voice_connected
                existing._callbacks["on_voice_disconnected"] = on_voice_disconnected
                existing._callbacks["on_voice_moved"] = self._on_voice_moved
                existing.join_voice(guild_id, channel_id)
                return existing
            existing.stop()

        connector = VoiceConnector(
            token=token,
            guild_id=guild_id,
            channel_id=channel_id,
            index=index,
            on_voice_connected=on_voice_connected,
            on_voice_disconnected=on_voice_disconnected,
            on_voice_moved=self._on_voice_moved,
            on_token_dead=self._on_token_dead,
            telemetry_enabled=self._telemetry_enabled,
            gateway_only=False,
        )
        self.voice_connectors[key] = connector
        connector.start()
        return connector

    def leave_channel(self, index, guild_id):
        """Leave đúng guild đó — các guild khác trong map giữ nguyên."""
        guild_id = str(guild_id)
        gw = self.gateway_connectors.get(index)
        if gw is not None:
            gw.leave_voice(guild_id)
            gw.gateway_only = not bool(gw.voice_channels)

        self._drop_legacy(index, guild_id)

    def get_gateway(self, index):
        return self.gateway_connectors.get(index)

    def set_callbacks(self, index, **callbacks):
        """Update gateway callback slots for one token.

        Passing ``None`` clears a slot; omitted slots are left untouched.
        Returns ``False`` when the token has no gateway connector yet.
        """
        gw = self.gateway_connectors.get(index)
        if gw is None:
            return False
        slots = getattr(gw, "_callbacks", None)
        if not isinstance(slots, dict):
            return False
        for name in (
            "on_ready",
            "on_voice_connected",
            "on_voice_disconnected",
            "on_voice_moved",
        ):
            if name in callbacks:
                slots[name] = callbacks[name]
        return True

    def set_default_on_voice_moved(self, callback):
        """Remember the move callback for connectors booted later."""
        self._on_voice_moved = callback

    def set_legacy_on_voice_moved(self, index, callback):
        """Update the move callback on every legacy connector for ``index``."""
        prefix = f"{index}_"
        updated = 0
        for key, connector in list(self.voice_connectors.items()):
            if not str(key).startswith(prefix):
                continue
            slots = getattr(connector, "_callbacks", None)
            if isinstance(slots, dict):
                slots["on_voice_moved"] = callback
                updated += 1
        return updated

    def get_all_voice_indices(self):
        """Return every gateway connector index (sorted, non-negative ints)."""
        indices = set()
        for key in self.gateway_connectors:
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indices.add(index)
        return sorted(indices)

    def get_voice(self, index, guild_id):
        gw = self.gateway_connectors.get(index)
        if gw is not None and str(guild_id) in getattr(gw, "voice_channels", {}):
            return gw
        return self.voice_connectors.get(f"{index}_{guild_id}")

    def is_gateway_ready(self, index):
        c = self.gateway_connectors.get(index)
        return c and c.connected

    def is_voice_connected(self, index, guild_id):
        guild_id = str(guild_id)
        gw = self.gateway_connectors.get(index)
        if gw is not None:
            channels = getattr(gw, "voice_channels", None)
            if channels is not None:
                if guild_id in channels:
                    return bool(gw.voice_connected)
            elif gw.guild_id == guild_id:
                return bool(gw.voice_connected)
        legacy = self.voice_connectors.get(f"{index}_{guild_id}")
        return bool(legacy and legacy.voice_connected)

    def get_all_voice(self, index):
        """Per-guild lightweight entries cho mọi map entry của token."""
        result = {}
        gw = self.gateway_connectors.get(index)
        if gw is not None:
            channels = getattr(gw, "voice_channels", None)
            if channels is not None:
                for guild_id, channel_id in list(channels.items()):
                    result[f"{index}_{guild_id}"] = SimpleNamespace(
                        voice_connected=True,
                        guild_id=str(guild_id),
                        channel_id=str(channel_id),
                    )
            elif gw.guild_id and not getattr(gw, "gateway_only", False):
                # Fallback cho connector cũ chỉ có 1 guild_id/channel_id.
                result[f"{index}_{gw.guild_id}"] = gw
        # Legacy voice connectors (không đè entry map).
        for key, connector in self.voice_connectors.items():
            if key.startswith(f"{index}_") and key not in result:
                result[key] = connector
        return result

    def _connectors_for(self, index):
        """Yield mọi connector của 1 token (gateway + voice connectors)."""
        gateway = self.gateway_connectors.get(index)
        if gateway is not None:
            yield gateway
        prefix = f"{index}_"
        for key, connector in self.voice_connectors.items():
            if key.startswith(prefix):
                yield connector

    def _is_in_voice(self, index, connector):
        """Gateway tính khi map có entry hoặc còn single-mode guild_id;
        voice connector cũ cần voice_connected."""
        if self.gateway_connectors.get(index) is connector:
            if getattr(connector, "voice_channels", None):
                return True
            return bool(connector.guild_id) and not getattr(connector, "gateway_only", False)
        return bool(getattr(connector, "voice_connected", False))

    def _gateway_voice_entries(self, index, connector):
        """Các guild_id cần áp dụng stream/camera trên gateway connector."""
        if self.gateway_connectors.get(index) is not connector:
            return None
        channels = getattr(connector, "voice_channels", None)
        if channels:
            return list(channels)
        return None

    def start_stream(self, index):
        """Bật Go Live trên mọi guild đang ở trong voice của token."""
        applied = False
        for connector in self._connectors_for(index):
            guilds = self._gateway_voice_entries(index, connector)
            if guilds is not None:
                for guild_id in guilds:
                    if connector.start_stream(guild_id):
                        applied = True
                continue
            if not self._is_in_voice(index, connector):
                continue
            if connector.start_stream():
                applied = True
        return applied

    def stop_stream(self, index):
        """Tắt Go Live trên mọi guild/connector đang stream hoặc trong voice."""
        applied = False
        for connector in self._connectors_for(index):
            guilds = self._gateway_voice_entries(index, connector)
            if guilds is not None:
                for guild_id in guilds:
                    if connector.stop_stream(guild_id):
                        applied = True
                continue
            if not (getattr(connector, "is_streaming", False)
                    or getattr(connector, "voice_connected", False)):
                continue
            if connector.stop_stream():
                applied = True
        return applied

    def set_camera(self, index, enabled):
        """Bật/tắt camera trên mọi guild đang ở trong voice của token."""
        applied = False
        for connector in self._connectors_for(index):
            guilds = self._gateway_voice_entries(index, connector)
            if guilds is not None:
                for guild_id in guilds:
                    if connector.set_camera(enabled, guild_id):
                        applied = True
                continue
            if not self._is_in_voice(index, connector):
                continue
            if connector.set_camera(enabled):
                applied = True
        return applied

    def update_voice_state(self, index, guild_id, channel_id=None,
                           self_mute=None, self_deaf=None):
        """Áp dụng mute/deafen/move cho mọi connector đang giữ guild."""
        applied = False
        for connector in self._connectors_for(index):
            update = getattr(connector, "update_voice_state", None)
            if not callable(update):
                continue
            try:
                if update(
                    guild_id,
                    channel_id=channel_id,
                    self_mute=self_mute,
                    self_deaf=self_deaf,
                ):
                    applied = True
            except Exception:
                continue
        return applied

    def get_voice_channels(self, index, guild_id):
        """Trả cache kênh của connector đầu tiên có dữ liệu cho guild."""
        for connector in self._connectors_for(index):
            getter = getattr(connector, "get_voice_channels", None)
            if not callable(getter):
                continue
            try:
                channels = getter(guild_id)
            except Exception:
                continue
            if channels:
                return channels
        return []

    def get_stream_flags(self, index):
        """OR cờ streaming/video trên mọi connector của token."""
        streaming = False
        video = False
        for connector in self._connectors_for(index):
            streaming = streaming or bool(getattr(connector, "is_streaming", False))
            video = video or bool(getattr(connector, "is_video", False))
        return {"streaming": streaming, "video": video}

    def stop_all(self):
        for c in self.gateway_connectors.values():
            c.stop()
        for c in self.voice_connectors.values():
            c.stop()
        self.gateway_connectors.clear()
        self.voice_connectors.clear()
        self.main_indices.clear()
