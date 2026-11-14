"""
Telemetry Anti-Flag — Gửi fake telemetry data để tránh bị Discord flag.
Port từ TelementryDiscordLib, thích ứng với discord.py-self.
"""

import time
import struct
import base64
import random
import uuid
import asyncio
import threading
import aiohttp
import logging
from datetime import datetime

from .client_identity import CLIENT_LOCALE, discord_headers

logger = logging.getLogger(__name__)

SCREEN_NAMES = ("friends", "guild", "dm", "settings", "store")
VIEWPORTS = ((1280, 720), (1920, 1080), (1536, 864), (1366, 768))


class Client_UUID:
    """Tạo UUID dựa trên user_id (từ discum)."""
    __slots__ = ['userID', 'randomPrefix', 'creationTime', 'UUID']

    def __init__(self, userID, creationTime="now"):
        self.userID = int(userID)
        num = int(4294967296 * random.random())
        self.randomPrefix = num if num <= 2147483647 else num - 4294967296
        self.creationTime = (
            int(time.mktime(datetime.now().timetuple()) * 1000)
            if creationTime == "now"
            else creationTime
        )
        self.UUID = ""

    def calculate(self, event_sequence_number):
        buf = bytearray(struct.pack('24x'))
        uid = self.userID
        buf[0:4] = struct.pack("<i", uid % 4294967296 if uid % 4294967296 <= 2147483647 else uid % 4294967296 - 4294967296)
        buf[4:8] = struct.pack("<i", uid >> 32 if (uid >> 32) <= 2147483647 else (uid >> 32) - 4294967296)
        buf[8:12] = struct.pack("<i", self.randomPrefix)
        ct = self.creationTime
        buf[12:16] = struct.pack("<i", ct % 4294967296 if ct % 4294967296 <= 2147483647 else ct % 4294967296 - 4294967296)
        buf[16:20] = struct.pack("<i", ct >> 32 if (ct >> 32) <= 2147483647 else (ct >> 32) - 4294967296)
        buf[20:24] = struct.pack("<i", event_sequence_number if event_sequence_number <= 2147483647 else event_sequence_number - 4294967296)
        self.UUID = base64.b64encode(buf).decode('ascii')
        return self.UUID


class TelemetrySender:
    """Gửi telemetry data để tránh bị Discord flag."""

    SCIENCE_URL = "https://discord.com/api/v9/science"

    def __init__(self, token: str, user_id: str, session_identity=None):
        self.token = token
        self.user_id = str(user_id)
        self.session_identity = session_identity
        self.analytics_token = None
        # Reuse the connector's session ids so IDENTIFY and telemetry events
        # describe the same browser session.
        identity = session_identity or {}
        self.session_id = identity.get(
            "client_heartbeat_session_id"
        ) or f"session_{uuid.uuid4().hex[:16]}"
        self.launch_signature = identity.get("launch_signature") or str(
            uuid.uuid4()
        )
        self.event_sequence = 5
        self.uuid_gen = Client_UUID(self.user_id)
        self.locale = CLIENT_LOCALE
        self._app_opened_at = time.time()
        self._periodic_task = None
        self._should_stop = False
        self._stop_event = threading.Event()

    def _make_base_props(self, extra=None):
        props = {
            "client_track_timestamp": int(time.time() * 1000),
            "client_heartbeat_session_id": self.session_id,
            "event_sequence_number": self.event_sequence,
            "success": True,
            "experimental_features": [],
            "client_performance_memory": 0,
            "accessibility_features": 256,
            "rendered_locale": self.locale,
            "uptime_app": max(
                0, int((time.time() - self._app_opened_at) * 1000)
            ),
            "launch_signature": self.launch_signature,
            "client_uuid": self.uuid_gen.calculate(self.event_sequence),
        }
        if extra:
            props.update(extra)
        return props

    async def _send(self, events: list):
        if not self.analytics_token:
            return
        payload = {
            "token": self.analytics_token,
            "events": events,
        }
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        headers.update(discord_headers(self.session_identity))
        try:
            # Per-send session: tạo + đóng trong CÙNG loop của lần gửi này.
            # (Thread telemetry tạo event loop mới mỗi chu kỳ — nếu tái dùng session
            # của loop cũ sẽ bị leak "Unclosed client session" mỗi 300s.)
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)) as session:
                await session.post(self.SCIENCE_URL, json=payload, headers=headers)
            # Chờ transport SSL đóng hẳn trước khi caller gọi loop.close()
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.debug("Telemetry send failed: %s", e)

    async def send_initial_events(self):
        if not self.analytics_token:
            return

        now = int(time.time() * 1000)
        events = []

        # 1. libdiscore_loaded
        self.event_sequence = 1
        events.append({
            "type": "libdiscore_loaded",
            "properties": self._make_base_props({
                "event_sequence_number": 1,
                "client_send_timestamp": now,
            }),
        })

        # 2. session_start_client
        self.event_sequence = 2
        events.append({
            "type": "session_start_client",
            "properties": self._make_base_props({
                "event_sequence_number": 2,
                "client_rtc_state": "DISCONNECTED",
                "client_app_state": "unfocused",
                "client_viewport_width": 1280,
                "client_viewport_height": 720,
                "client_send_timestamp": now,
            }),
        })

        # 3. app_ui_viewed
        self.event_sequence = 3
        events.append({
            "type": "app_ui_viewed",
            "properties": self._make_base_props({
                "event_sequence_number": 3,
                "total_compressed_byte_size": 11149616,
                "total_uncompressed_byte_size": 53463101,
                "total_transfer_byte_size": 0,
                "js_compressed_byte_size": 7349364,
                "js_uncompressed_byte_size": 36652103,
                "js_transfer_byte_size": 0,
                "css_compressed_byte_size": 667380,
                "css_uncompressed_byte_size": 4550726,
                "css_transfer_byte_size": 0,
                "load_id": str(uuid.uuid4()),
                "screen_name": "friends",
                "duration_ms_since_app_opened": 2833,
                "app_hardware_acceleration_enabled": True,
                "client_rtc_state": "DISCONNECTED",
                "client_app_state": "unfocused",
                "client_viewport_width": 1280,
                "client_viewport_height": 720,
                "client_send_timestamp": now,
            }),
        })

        # 4. ready_payload_received
        self.event_sequence = 4
        events.append({
            "type": "ready_payload_received",
            "properties": self._make_base_props({
                "event_sequence_number": 4,
                "compressed_byte_size": 13378,
                "uncompressed_byte_size": 53363,
                "compression_algorithm": "zlib-stream",
                "packing_algorithm": "json",
                "unpack_duration_ms": 1,
                "identify_total_server_duration_ms": 336,
                "identify_api_duration_ms": 260,
                "num_guilds": 1,
                "num_guild_channels": 4,
                "is_reconnect": False,
                "is_fast_connect": False,
                "client_rtc_state": "DISCONNECTED",
                "client_app_state": "unfocused",
                "client_viewport_width": 1280,
                "client_viewport_height": 720,
                "client_send_timestamp": now,
            }),
        })

        # 5. dm_list_viewed
        self.event_sequence = 5
        events.append({
            "type": "dm_list_viewed",
            "properties": self._make_base_props({
                "event_sequence_number": 5,
                "accessibility_features": 524544,
                "accessibility_support_enabled": False,
                "num_users_visible": 0,
                "num_users_visible_with_mobile_indicator": 0,
                "client_send_timestamp": now,
            }),
        })

        await self._send(events)

    async def send_periodic(self):
        """Gửi 1 event định kỳ với giá trị thay đổi tự nhiên."""
        if not self.analytics_token:
            return
        self.event_sequence += 1
        now = int(time.time() * 1000)
        screen_name = random.choice(SCREEN_NAMES)
        viewport_width, viewport_height = random.choice(VIEWPORTS)
        app_state = random.choice(("focused", "unfocused"))
        duration = max(
            0,
            int((time.time() - self._app_opened_at) * 1000)
            + random.randint(-500, 500),
        )
        event = {
            "type": "app_ui_viewed",
            "properties": self._make_base_props({
                "event_sequence_number": self.event_sequence,
                "total_compressed_byte_size": max(
                    0, 11149616 + random.randint(-250000, 250000)
                ),
                "total_uncompressed_byte_size": max(
                    0, 53463101 + random.randint(-500000, 500000)
                ),
                "total_transfer_byte_size": 0,
                "js_compressed_byte_size": max(
                    0, 7349364 + random.randint(-100000, 100000)
                ),
                "js_uncompressed_byte_size": max(
                    0, 36652103 + random.randint(-300000, 300000)
                ),
                "js_transfer_byte_size": 0,
                "css_compressed_byte_size": max(
                    0, 667380 + random.randint(-20000, 20000)
                ),
                "css_uncompressed_byte_size": max(
                    0, 4550726 + random.randint(-50000, 50000)
                ),
                "css_transfer_byte_size": 0,
                "load_id": str(uuid.uuid4()),
                "screen_name": screen_name,
                "duration_ms_since_app_opened": duration,
                "app_hardware_acceleration_enabled": True,
                "client_rtc_state": "DISCONNECTED",
                "client_app_state": app_state,
                "client_viewport_width": viewport_width,
                "client_viewport_height": viewport_height,
                "client_send_timestamp": now,
            }),
        }
        await self._send([event])

    def start_periodic(self, interval=300):
        """Start background task gửi telemetry mỗi interval giây (thread-based)."""
        if self._periodic_task and self._periodic_task.is_alive():
            return
        self._should_stop = False
        self._stop_event.clear()
        self._periodic_task = threading.Thread(target=self._thread_loop, args=(interval,), daemon=True)
        self._periodic_task.start()

    def _thread_loop(self, interval):
        """Periodic loop chạy trong thread riêng — Event.wait để stop được NGAY."""
        while not self._should_stop:
            # Jitter ±15% để không tạo pattern đúng 300s mỗi lần.
            wait = max(30.0, interval * (1 + random.uniform(-0.15, 0.15)))
            if self._stop_event.wait(wait):
                break
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.send_periodic())
                loop.close()
            except Exception:
                pass

    def stop_periodic(self):
        """Dừng background telemetry thread."""
        self._should_stop = True
        self._stop_event.set()
        if self._periodic_task and self._periodic_task.is_alive():
            self._periodic_task.join(timeout=5)


