import discord
from discord.ext import commands
import asyncio
import re

from src.http_client import api_request
from src.utils import try_delete
import json
import logging
import random
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SERVICE_PLATFORM = {
    "desktop":    discord.ActivityPlatform.desktop,
    "xbox":       discord.ActivityPlatform.xbox,
    "samsung":    discord.ActivityPlatform.samsung,
    "ios":        discord.ActivityPlatform.ios,
    "android":    discord.ActivityPlatform.android,
    "embedded":   discord.ActivityPlatform.embedded,
    "ps4":        discord.ActivityPlatform.ps4,
    "ps5":        discord.ActivityPlatform.ps5,
    "meta":       discord.ActivityPlatform.meta_quest,  # alias ngắn cho meta_quest
    "meta_quest": discord.ActivityPlatform.meta_quest,
}

ACTIVITY_TYPES = {
    "playing": 0, "streaming": 1, "listening": 2,
    "watching": 3, "competing": 5,
}

STATUS_MAP = {
    "online":    discord.Status.online,
    "idle":      discord.Status.idle,
    "dnd":       discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

DEFAULT_ALBUM_ART = "ab67616d00001e02c4d671473910340ec095a9cc"
DEFAULT_TRACK_MS = 210000

# Discord CDN assets are converted to ``mp:`` by discord.py automatically;
# every other external http(s) image must be resolved through the API first.
_DISCORD_CDN_RE = re.compile(
    r"https?://(?:cdn|media|images-ext-\d+)\.discordapp\.(?:com|net)/",
    re.IGNORECASE,
)


def parse_spotify_track(track) -> dict:
    """Normalize one ``data/songs.json`` entry into the fields Spotify uses.

    Flat form (one object per song)::

        {"name": "...", "artist": "...", "id": "<spotify track id>",
         "duration_ms": 147272, "image": "<hash or i.scdn.co URL>",
         "album": "..."}

    Only ``name`` is required.  ``album`` defaults to the song name, the
    artwork hash falls back to built-in album art, the duration falls back to
    3.5 minutes, and the Play button URL is derived from the track id.
    """

    if not isinstance(track, dict):
        track = {}

    name = str(track.get("name") or "Unknown")
    artist = str(track.get("artist") or "Unknown")
    album = str(track.get("album") or name)

    raw_duration = track.get("duration_ms")
    if isinstance(raw_duration, bool):
        raw_duration = None
    try:
        duration_ms = int(raw_duration or DEFAULT_TRACK_MS)
    except (TypeError, ValueError):
        duration_ms = DEFAULT_TRACK_MS
    if duration_ms <= 0:
        duration_ms = DEFAULT_TRACK_MS

    image = str(track.get("image") or "").strip()
    if image.startswith("https://i.scdn.co/image/"):
        image = image.split("https://i.scdn.co/image/", 1)[1]
    if not image:
        image = DEFAULT_ALBUM_ART

    track_id = str(track.get("id") or "").strip()
    spotify_url = (
        f"https://open.spotify.com/track/{track_id}"
        if track_id
        else "https://open.spotify.com"
    )

    return {
        "name": name,
        "artist": artist,
        "album": album,
        "duration_ms": duration_ms,
        "image": image,
        "id": track_id,
        "spotify_url": spotify_url,
    }


class Presence(commands.Cog):
    """Custom status, Spotify, Rich Presence manager."""

    def __init__(self, bot, token: str):
        self.bot   = bot
        self.token = token

        self.songs_file = "data/songs.json"
        self.rpc_config = "data/rich_presence.json"

        self.is_rotating        = False
        self.is_rotating_listen = False
        self.is_custom_rpc      = False
        self._rotate_task  = None
        self._spotify_task = None
        self._rpc_task     = None

        self.statuses = []
        self.tracks   = []
        self._rotate_status = "online"  # status dùng khi rotate (lấy từ rich_presence.json)

        # ✅ Lưu presence hiện tại để gửi lại khi reconnect
        self._current_presence  = None
        self._current_status    = "online"
        self._current_rpc       = None   # (activity hoặc list activities, status_str) để gửi lại khi reconnect
        # Status gốc TRƯỚC khi bật RPC — dùng để restore khi tắt (không ép online)
        self._pre_rpc_status    = None

        # ✅ Chặn auto-apply lại sau khi user TẮT presence thủ công
        # (reconnect sau khi loop chết vẫn auto-apply lại bình thường)
        self._manually_cleared = False
        # Cache kết quả resolve external asset: "app_id:url" -> "mp:..."
        self._asset_cache = {}

    # ==================== RECONNECT HANDLER ====================

    @commands.Cog.listener()
    async def on_ready(self):
        """Gửi lại presence khi bot reconnect."""
        # Chỉ re-send RPC nếu user CHƯA tắt (race guard với `custom_rpc off`)
        if self._current_rpc and self.is_custom_rpc:
            try:
                activity, status = self._current_rpc
                await self._send_presence(
                    activity if isinstance(activity, list) else [activity],
                    status,
                )
            except Exception:
                pass
        elif self._current_presence:
            try:
                await self._send_presence(self._current_presence, self._current_status)
            except Exception:
                pass

        # Reconnect recovery: re-apply the config on every ready unless the
        # user manually stopped the presence or a loop is already running.
        if (
            not self._manually_cleared
            and not self.is_custom_rpc
            and not self.is_rotating_listen
            and not self.is_rotating
        ):
            try:
                cfg = self._load_json(self.rpc_config)
                if (
                    isinstance(cfg, dict)
                    and cfg
                    and cfg.get("enabled", True) is not False
                ):
                    await self.apply_config()
            except Exception:
                logger.debug(
                    "[PRESENCE] reconnect auto-apply failed", exc_info=True
                )

    # ==================== HELPERS ====================

    def _load_json(self, path, default=None):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default

    async def _send_presence(self, activity, status: str = "online") -> bool:
        """Send raw presence via WebSocket opcode 3.

        ``activity`` may be a single activity dict or a list of activity
        dicts (custom activities stacked with the Spotify card).  Returns
        ``True`` when the payload reached the socket successfully.
        """
        # ✅ Lưu lại để dùng khi reconnect
        self._current_presence = activity
        self._current_status   = status
        activities = activity if isinstance(activity, list) else [activity]
        try:
            await self.bot.ws.send_as_json({
                "op": 3,
                "d": {
                    "since": None,
                    "activities": activities,
                    "status": status,
                    "afk": False
                }
            })
            return True
        except Exception as e:
            logger.error("[SEND_PRESENCE] %s", e)
            return False

    async def _clear_presence(self, status: str | None = None):
        """Clear presence via WebSocket opcode 3.
        status: nếu None, dùng _pre_rpc_status (nếu có), fallback "online"."""
        self._current_presence = None
        # Status: ưu tiên arg > _pre_rpc_status > fallback "online"
        effective_status = status or self._pre_rpc_status or "online"
        self._current_status   = effective_status
        try:
            await self.bot.ws.send_as_json({
                "op": 3,
                "d": {
                    "since": None,
                    "activities": [],
                    "status": effective_status,
                    "afk": False
                }
            })
        except Exception:
            pass

    async def _clear_status(self):
        """Clear custom status via REST — dùng shared api_request (429-retry)."""
        status, _ = await api_request(
            "PATCH",
            "https://discord.com/api/v10/users/@me/settings",
            token=self.token,
            json_body={"custom_status": None},
        )
        if status not in (200, 204):
            logger.warning("[CLEAR_STATUS] HTTP %s", status)

    def _stop_all(self):
        self.is_rotating        = False
        self.is_rotating_listen = False
        self.is_custom_rpc      = False
        # Cancel tasks — tránh 2 loop presence chạy đè nhau
        for task in (self._rotate_task, self._spotify_task, self._rpc_task):
            if task and not task.done():
                task.cancel()
        self._rotate_task  = None
        self._spotify_task = None
        self._rpc_task     = None

    @staticmethod
    async def _stop_task(task):
        """Cancel task và CHỜ nó chết hẳn — tránh 2 loop presence chạy đè nhau."""
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def cog_unload(self):
        self._stop_all()
        # Giữ reference task — tránh bị GC giữa chừng ("Task was destroyed but it is pending")
        try:
            self._clear_task = asyncio.create_task(self._clear_presence())
        except RuntimeError:
            pass  # loop đang đóng — không cần clear nữa

    # ==================== SAFE SLEEP (thoát ngay khi stop) ====================

    async def _safe_sleep(self, total_seconds: float, flag_check) -> bool:
        """
        Sleep theo từng tick 5s.
        Trả về True nếu hết giờ bình thường.
        Trả về False nếu bị stop giữa chừng.
        """
        elapsed = 0
        tick    = 5
        while elapsed < total_seconds:
            if not flag_check():
                return False
            await asyncio.sleep(min(tick, total_seconds - elapsed))
            elapsed += tick
        return True

    # ==================== CUSTOM STATUS ====================
    @commands.command(name='rotate')
    async def rotate(self, ctx, *, statuses: str):
        """Usage: {prefix}rotate <emoji,text / emoji,text2> | {prefix}rotate off — rotate status"""
        await try_delete(ctx.message)
        if statuses.strip().lower() in ("off", "stop"):
            return await self._stop_rotation(ctx)
        if self.is_custom_rpc:
            t = await ctx.send(f"**❌ Custom RPC is running** — use `{ctx.prefix}rpc off` first")
            await asyncio.sleep(4); await t.delete(); return
        if self.is_rotating:
            t = await ctx.send("**❌ Status rotation is already running**")
            await asyncio.sleep(3); await t.delete(); return

        self.statuses = [s.strip() for s in statuses.split('/') if s.strip()]
        if not self.statuses:
            t = await ctx.send(f"**❌ Usage:** `{ctx.prefix}rotate 😎,Text1 / 🔥,Text2`")
            await asyncio.sleep(4); await t.delete(); return

        # Tôn trọng status (online/idle/dnd/invisible) từ rich_presence.json
        cfg = self._load_json(self.rpc_config, {}) or {}
        rotate_status = str(cfg.get("status", "online")).lower()
        self._rotate_status = rotate_status if rotate_status in STATUS_MAP else "online"

        self.is_rotating = True
        t = await ctx.send(
            f"**✅ Status Rotation Enabled** — `{len(self.statuses)}` statuses, "
            f"switching every 30s, status: `{self._rotate_status}`"
        )
        await asyncio.sleep(3); await t.delete()
        self._rotate_task = asyncio.create_task(self._rotate_loop())

    async def _stop_rotation(self, ctx):
        """Disable status rotation — used by .rotate off."""
        self.is_rotating = False
        await self._stop_task(self._rotate_task)
        self._rotate_task = None
        await self._clear_status()
        t = await ctx.send("**✅ Status rotation disabled**")
        await asyncio.sleep(3); await t.delete()

    @staticmethod
    def _parse_custom_status(entry: str) -> tuple[str, str | None, str | None]:
        """Split one 'emoji,text' entry into (text, emoji_id, emoji_name)."""
        parts = entry.split(',', 1)
        emoji = parts[0].strip()
        text = parts[1].strip() if len(parts) > 1 else ""

        if emoji.startswith("<") and emoji.endswith(">"):
            ep = emoji.strip("<>").split(":")
            if len(ep) >= 3:
                return text, ep[2], ep[1]
            return text, ep[1] if len(ep) == 2 else None, ep[0]
        if emoji.isdigit():
            return text, emoji, None
        return text, None, emoji

    async def _apply_custom_status(self, entry: str) -> None:
        text, emoji_id, emoji_name = self._parse_custom_status(entry)
        status, _ = await api_request(
            "PATCH",
            "https://discord.com/api/v10/users/@me/settings",
            token=self.token,
            json_body={
                "status": self._rotate_status,
                "custom_status": {"text": text, "emoji_name": emoji_name, "emoji_id": emoji_id},
            },
        )
        if status not in (200, 204):
            logger.warning("[ROTATE] HTTP %s khi cập nhật status", status)

    async def _rotate_loop(self):
        while self.is_rotating:
            try:
                for status in self.statuses:
                    if not self.is_rotating:
                        break
                    await self._apply_custom_status(status)
                    if not await self._safe_sleep(30, lambda: self.is_rotating):
                        break
            except Exception as e:
                logger.error("[ROTATE] %s", e)
                await asyncio.sleep(5)
        # Clear is issued by _stop_rotation (the loop is cancelled before it can
        # reach this point, so a trailing clear here would either never run or
        # double-PATCH the settings endpoint).

    # ==================== SPOTIFY ====================

    @commands.command(name='spotify', aliases=['rotate_listen'])
    async def spotify(self, ctx, mode: str = None):
        """Usage: {prefix}spotify <on/off> — enable/disable Spotify impersonation"""
        await try_delete(ctx.message)

        # OFF → stop
        if mode and mode.lower() == "off":
            if not self.is_rotating_listen:
                t = await ctx.send("**❌ Spotify mode is not running**")
                await asyncio.sleep(3); await t.delete(); return
            self.is_rotating_listen = False
            await self._stop_task(self._spotify_task)
            self._spotify_task = None
            await self._clear_presence()
            t = await ctx.send("**✅ Spotify mode disabled**")
            await asyncio.sleep(3); await t.delete()
            return

        # ON hoặc không có tham số → start
        if self.is_rotating_listen:
            t = await ctx.send("**❌ Spotify mode is already running**")
            await asyncio.sleep(3); await t.delete(); return

        # Tắt custom_rpc và CHỜ loop cũ chết hẳn trước khi bật Spotify
        self.is_custom_rpc = False
        self._current_rpc = None  # không gửi lại RPC cũ sau reconnect đè Spotify
        await self._stop_task(self._rpc_task)
        self._rpc_task = None

        tracks = self._load_json(self.songs_file, [])
        if not isinstance(tracks, list) or not tracks:
            t = await ctx.send(f"**❌ No tracks found** — File: `{self.songs_file}`")
            await asyncio.sleep(5); await t.delete(); return

        self.tracks = tracks.copy()
        random.shuffle(self.tracks)
        self.is_rotating_listen = True
        t = await ctx.send(f"**✅ Spotify Mode Enabled** — 🎵 `{len(tracks)}` tracks shuffled")
        await asyncio.sleep(3); await t.delete()
        self._spotify_task = asyncio.create_task(self._spotify_loop())

    async def _spotify_loop(self, custom_activities=None):
        REFRESH = 60  # gửi lại presence mỗi 60s
        custom_payloads = self._activity_payloads(custom_activities or [])

        while self.is_rotating_listen:
            try:
                if not self.tracks:
                    self.tracks = self._load_json(self.songs_file, [])
                    random.shuffle(self.tracks)
                if not self.tracks:
                    await asyncio.sleep(10); continue

                track       = self.tracks.pop(0)
                fields      = parse_spotify_track(track)
                name        = fields["name"]
                artist      = fields["artist"]
                album       = fields["album"]
                img         = fields["image"]
                duration_ms = fields["duration_ms"]
                spotify_url = fields["spotify_url"]
                start       = int(datetime.now(timezone.utc).timestamp() * 1000)
                end         = start + duration_ms

                # Chuẩn Discord: party id là spotify:{user_id} (không random)
                user = getattr(getattr(self, "bot", None), "user", None)
                user_id = getattr(user, "id", None)
                party_id = (
                    f"spotify:{user_id}"
                    if user_id
                    else f"spotify:{random.randint(100000000000, 999999999999)}"
                )

                payload = {
                    "type": 2,
                    "name": "Spotify",
                    "details": name,
                    "state": f"by {artist}",
                    "timestamps": {"start": start, "end": end},
                    "assets": {"large_image": f"spotify:{img}", "large_text": album},
                    # Spotify app ID thật của Discord (bản cũ dùng ID sai)
                    "application_id": 172150925382486016,
                    "party":   {"id": party_id},
                    "sync_id": fields["id"] or str(random.randint(100000, 999999)),
                    "flags":   48,
                    "buttons":  ["Play on Spotify"],
                    "metadata": {"button_urls": [spotify_url]},
                }

                # ✅ Gửi lại định kỳ suốt thời gian bài hát (chỉ khi cần)
                elapsed = 0
                last_sent = None
                while self.is_rotating_listen and elapsed < duration_ms / 1000:
                    ws_session = getattr(
                        getattr(self.bot, "ws", None), "session_id", None
                    )
                    key = (custom_payloads, payload, ws_session)
                    if key != last_sent:
                        if await self._send_presence(
                            [*custom_payloads, payload]
                        ):
                            last_sent = key
                    slept = await self._safe_sleep(REFRESH, lambda: self.is_rotating_listen)
                    if not slept:
                        break
                    elapsed += REFRESH

            except Exception as e:
                logger.error("[SPOTIFY] %s", e)
                await asyncio.sleep(10)

        await self._clear_presence()

    # ==================== CUSTOM RPC ====================

    @staticmethod
    def _activity_type(item) -> int:
        return ACTIVITY_TYPES.get(str(item.get("type") or "playing").lower(), 0)

    @staticmethod
    def _application_id(value):
        """Return a numeric application id, or ``None`` when it is not digits."""
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip()
        return int(text) if text.isdigit() else None

    @staticmethod
    def _activity_buttons(raw_buttons) -> list:
        """Build up to two valid :class:`discord.ActivityButton` objects."""
        buttons = []
        if not isinstance(raw_buttons, list):
            return buttons
        for entry in raw_buttons:
            if len(buttons) >= 2:
                break
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            url = str(entry.get("url") or "").strip()
            if not label or not url.lower().startswith(("http://", "https://")):
                continue
            buttons.append(discord.ActivityButton(label=label, url=url))
        return buttons

    @staticmethod
    def _activity_assets(item, act_type: int) -> dict:
        """Return ``ActivityAssets`` keyword arguments for one activity."""
        assets_kw = {}
        large_image = str(item.get("large_image") or "").strip()
        if large_image:
            assets_kw["large_image"] = large_image
            large_text = str(item.get("large_text") or "").strip()
            # Listening renders large_text as a visible line (the album line).
            if large_text:
                assets_kw["large_text"] = large_text
        small_image = str(item.get("small_image") or "").strip()
        if small_image:
            assets_kw["small_image"] = small_image
            small_text = str(item.get("small_text") or "").strip()
            if small_text:
                assets_kw["small_text"] = small_text
        return assets_kw

    @staticmethod
    def _elapsed_start(item):
        """Return ``now - elapsed_hours`` (clamped to 0..8760, default 1)."""
        raw_hours = item.get("elapsed_hours", 1)
        if isinstance(raw_hours, bool):
            raw_hours = 1
        try:
            hours = float(raw_hours)
        except (TypeError, ValueError):
            hours = 1.0
        if hours != hours:  # NaN
            hours = 1.0
        hours = max(0.0, min(hours, 8760.0))
        return datetime.now(timezone.utc) - timedelta(hours=hours)

    @staticmethod
    def _end_minutes(item):
        """Return now + end_minutes (clamped 1..1440, default 30)."""
        raw = item.get("end_minutes", 30)
        if isinstance(raw, bool):
            raw = 30
        try:
            minutes = float(raw)
        except (TypeError, ValueError):
            minutes = 30.0
        if minutes != minutes:  # NaN
            minutes = 30.0
        minutes = max(1.0, min(minutes, 1440.0))
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)

    @staticmethod
    def _duration_minutes(item):
        """Return the progress-bar duration in minutes (0 = disabled)."""
        raw = item.get("duration_minutes", 0)
        if isinstance(raw, bool):
            raw = 0
        try:
            minutes = float(raw)
        except (TypeError, ValueError):
            minutes = 0.0
        if minutes != minutes:  # NaN
            minutes = 0.0
        return max(0.0, min(minutes, 1440.0))

    @staticmethod
    def _stream_url(item, act_type: int):
        """Return a valid streaming URL (Discord requires one for type 1)."""
        if act_type != 1:
            return None
        url = str(item.get("url") or "").strip()
        if url.startswith(
            (
                "https://twitch.tv/",
                "https://www.twitch.tv/",
                "https://youtube.com/",
                "https://www.youtube.com/",
            )
        ):
            return url
        return None

    def _build_activity_objects(self, cfg) -> list:
        """Build the activities described by a dashboard or legacy config."""
        if not isinstance(cfg, dict):
            return []

        raw_activities = cfg.get("activities")
        if isinstance(raw_activities, list):
            # An explicit list (even empty) is the dashboard schema: zero
            # activities means "nothing to show", not the legacy flat config.
            activities = []
            for item in raw_activities:
                if len(activities) >= 3:
                    break
                if not isinstance(item, dict):
                    continue
                try:
                    act_type = self._activity_type(item)
                    assets_kw = self._activity_assets(item, act_type)
                    ts_kwargs = {}
                    if item.get("show_elapsed", True):
                        ts_kwargs["start"] = self._elapsed_start(item)
                    if act_type in (2, 3):
                        duration = self._duration_minutes(item)
                        if duration > 0 and "start" in ts_kwargs:
                            # Progress bar: end = start + duration.
                            ts_kwargs["end"] = ts_kwargs["start"] + timedelta(
                                minutes=duration
                            )
                        elif item.get("show_end"):
                            ts_kwargs["end"] = self._end_minutes(item)
                    timestamps = (
                        discord.ActivityTimestamps(**ts_kwargs)
                        if ts_kwargs
                        else None
                    )
                    activities.append(
                        discord.Activity(
                            application_id=self._application_id(
                                item.get("application_id")
                            ),
                            type=discord.ActivityType(act_type),
                            name=str(item.get("name") or "Discord"),
                            details=str(item.get("details") or ""),
                            state=str(item.get("state") or ""),
                            url=self._stream_url(item, act_type),
                            buttons=self._activity_buttons(item.get("buttons")),
                            timestamps=timestamps,
                            platform=SERVICE_PLATFORM.get(
                                str(item.get("platform") or "").lower()
                            ),
                            assets=(
                                discord.ActivityAssets(**assets_kw)
                                if assets_kw
                                else None
                            ),
                        )
                    )
                except Exception:
                    logger.debug(
                        "[CUSTOM RPC] Skipping invalid activity", exc_info=True
                    )
            return activities

        # Legacy flat config: one activity, same shape as the old loop.
        act_type = self._activity_type(cfg)
        name_text = cfg.get("name") or ""
        details_text = cfg.get("details") or ""
        platform_name = str(cfg.get("platform") or "").strip()
        if not platform_name:
            # Không có tên để hiển thị — đừng dựng card "Discord" giả.
            return []
        details = str(name_text or details_text or platform_name)
        state = str(details_text) if name_text else None
        service = str(cfg.get("service") or "").lower()
        assets_kw = self._activity_assets(cfg, act_type)
        try:
            return [
                discord.Activity(
                    application_id=self._application_id(
                        cfg.get("application_id")
                    ),
                    type=discord.ActivityType(act_type),
                    name=platform_name,
                    details=details,
                    state=state,
                    buttons=self._activity_buttons(cfg.get("buttons")),
                    timestamps=discord.ActivityTimestamps(
                        start=datetime.now(timezone.utc)
                    ),
                    platform=SERVICE_PLATFORM.get(service),
                    assets=(
                        discord.ActivityAssets(**assets_kw)
                        if assets_kw
                        else None
                    ),
                )
            ]
        except Exception:
            logger.error(
                "[CUSTOM RPC] Could not build legacy activity", exc_info=True
            )
            return []

    async def _resolve_external_asset(self, url, app_id) -> str | None:
        """Resolve one external image URL to a Discord ``mp:`` asset path."""
        key = f"{app_id}:{url}"
        if key in self._asset_cache:
            return self._asset_cache[key]
        try:
            status, data = await api_request(
                "POST",
                f"https://discord.com/api/v10/applications/{app_id}/external-assets",
                token=self.token,
                json_body={"urls": [url]},
            )
            if status == 200 and isinstance(data, list) and data:
                path = (
                    data[0].get("external_asset_path")
                    if isinstance(data[0], dict)
                    else None
                )
                if path:
                    result = "mp:" + path
                    if len(self._asset_cache) >= 64:
                        self._asset_cache.pop(next(iter(self._asset_cache)))
                    self._asset_cache[key] = result
                    return result
        except Exception:
            logger.debug("[PRESENCE] external asset resolve failed", exc_info=True)
        return None

    async def _resolve_activity_assets(self, cfg) -> dict:
        """Return a copy of ``cfg`` with external image URLs replaced by ``mp:``."""
        if not isinstance(cfg, dict):
            return cfg

        raw_activities = cfg.get("activities")
        if isinstance(raw_activities, list) and raw_activities:
            changed = False
            activities = []
            for item in raw_activities:
                if not isinstance(item, dict):
                    activities.append(item)
                    continue
                app_id = self._application_id(item.get("application_id"))
                if app_id is None:
                    activities.append(item)
                    continue
                new_item = item
                for field in ("large_image", "small_image"):
                    url = str(item.get(field) or "").strip()
                    if not url.lower().startswith(("http://", "https://")):
                        continue
                    if _DISCORD_CDN_RE.match(url):
                        continue
                    mp = await self._resolve_external_asset(url, app_id)
                    if mp:
                        if new_item is item:
                            new_item = dict(item)
                        new_item[field] = mp
                        changed = True
                    else:
                        logger.warning(
                            "[PRESENCE] Could not resolve external image %s "
                            "via app %s — the card will show no image",
                            url,
                            app_id,
                        )
                activities.append(new_item)
            if not changed:
                return cfg
            clean = dict(cfg)
            clean["activities"] = activities
            return clean

        # Legacy flat config: one activity at the top level.
        app_id = self._application_id(cfg.get("application_id"))
        if app_id is None:
            return cfg
        clean = None
        for field in ("large_image", "small_image"):
            url = str(cfg.get(field) or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            if _DISCORD_CDN_RE.match(url):
                continue
            mp = await self._resolve_external_asset(url, app_id)
            if mp:
                if clean is None:
                    clean = dict(cfg)
                clean[field] = mp
            else:
                logger.warning(
                    "[PRESENCE] Could not resolve external image %s via app %s "
                    "— the card will show no image",
                    url,
                    app_id,
                )
        return clean if clean is not None else cfg

    @staticmethod
    def _activity_payloads(activities):
        """Convert activities to raw op3 dicts.

        ``session_id`` is a received-only field: the server stamps the real
        gateway session and it cannot be set by the client.  Viewers resolve
        button URLs through
        ``/users/{id}/sessions/{session_id}/activities/{app_id}/metadata``,
        so sending a fake session id breaks (or cross-wires) that lookup.
        Cards are separated by their application identity, not by sessions.
        """
        payloads = []
        for activity in activities:
            data = activity.to_dict()
            data.setdefault("flags", 1)
            payloads.append(data)
        return payloads

    async def apply_config(self) -> bool:
        """Apply ``self.rpc_config`` to the main account."""
        # An explicit apply re-enables reconnect recovery.
        self._manually_cleared = False
        cfg = self._load_json(self.rpc_config) or {}
        if not isinstance(cfg, dict) or not cfg:
            # Missing/corrupt config: never apply a phantom presence.
            await self.clear_presence()
            return False

        if cfg.get("enabled", True) is False:
            await self.clear_presence()
            return False

        status = str(cfg.get("status") or "online").lower()
        if status not in STATUS_MAP:
            status = "online"

        # One presence loop at a time: stop both before starting either.
        self.is_custom_rpc = False
        self.is_rotating_listen = False
        await self._stop_task(self._rpc_task)
        await self._stop_task(self._spotify_task)
        self._rpc_task = None
        self._spotify_task = None

        mode = str(cfg.get("mode") or "custom").lower()
        if mode == "spotify":
            tracks = self._load_json(self.songs_file, [])
            if not isinstance(tracks, list) or not tracks:
                await self.clear_presence()
                return False
            custom_activities = []
            if cfg.get("activities"):
                resolved = await self._resolve_activity_assets(cfg)
                custom_activities = self._build_activity_objects(resolved)
            self.tracks = tracks.copy()
            random.shuffle(self.tracks)
            self.is_rotating_listen = True
            self._spotify_task = asyncio.create_task(
                self._spotify_loop(custom_activities)
            )
            return True

        cfg = await self._resolve_activity_assets(cfg)
        activities = self._build_activity_objects(cfg)
        if not activities:
            await self.clear_presence()
            return False
        self.is_custom_rpc = True
        self._rpc_task = asyncio.create_task(
            self._custom_rpc_loop_v2(activities, status)
        )
        return True

    async def clear_presence(self):
        """Stop both presence loops and clear the main account activity."""
        # A manual clear must block reconnect auto-apply.
        self._manually_cleared = True
        self.is_custom_rpc = False
        self.is_rotating_listen = False
        await self._stop_task(self._rpc_task)
        await self._stop_task(self._spotify_task)
        self._rpc_task = None
        self._spotify_task = None
        self._current_rpc = None
        await self._clear_presence()

    @commands.command(name='rpc', aliases=['custom_rpc'])
    async def rpc(self, ctx, mode: str = None, status: str = None):
        """Usage: {prefix}rpc <on/off> [status] — enable/disable custom RPC"""
        await try_delete(ctx.message)

        # OFF → stop
        if mode and mode.lower() == "off":
            if not self.is_custom_rpc and not self.is_rotating_listen:
                t = await ctx.send("**❌ Custom RPC is not running**")
                await asyncio.sleep(3); await t.delete(); return
            await self.clear_presence()
            # Reset pre_rpc_status sau khi clear xong
            self._pre_rpc_status = None
            t = await ctx.send("**✅ Custom RPC disabled**")
            await asyncio.sleep(3); await t.delete()
            return

        # ON hoặc không có tham số → start
        if self.is_custom_rpc:
            t = await ctx.send("**❌ Custom RPC is already running**")
            await asyncio.sleep(3); await t.delete(); return
        if self.is_rotating:
            t = await ctx.send(f"**❌ Status rotation is running** — use `{ctx.prefix}rotate off` first")
            await asyncio.sleep(4); await t.delete(); return

        cfg = self._load_json(self.rpc_config)
        if not isinstance(cfg, dict) or not cfg:
            t = await ctx.send(f"**❌ Config not found** — File: `{self.rpc_config}`")
            await asyncio.sleep(5); await t.delete(); return

        # Lưu status hiện tại TRƯỚC khi bật RPC — để khôi phục khi tắt
        try:
            current = self.bot.user.status if self.bot and self.bot.user else None
            self._pre_rpc_status = str(current).lower() if current else "online"
        except Exception:
            self._pre_rpc_status = "online"

        if not await self.apply_config():
            t = await ctx.send(
                f"**❌ Custom RPC could not start** — check `{self.rpc_config}`"
            )
            await asyncio.sleep(5); await t.delete(); return

        service = str(cfg.get("service", "")).lower()
        effective_status = str(cfg.get("status") or "online").lower()
        if effective_status not in STATUS_MAP:
            effective_status = "online"
        t = await ctx.send(
            f"**✅ Custom RPC Enabled** — service: `{service or 'none'}` | status: `{effective_status}`"
        )
        await asyncio.sleep(3); await t.delete()

    async def _custom_rpc_loop_v2(self, activities, status):
        payloads = self._activity_payloads(activities)
        last_sent = None
        try:
            while self.is_custom_rpc:
                try:
                    ws_session = getattr(
                        getattr(self.bot, "ws", None), "session_id", None
                    )
                    key = (payloads, status, ws_session)
                    if key != last_sent:
                        if await self._send_presence(payloads, status):
                            self._current_rpc = (payloads, status)
                            last_sent = key
                except Exception:
                    logger.warning(
                        "[CUSTOM RPC] presence send failed; retrying next cycle",
                        exc_info=True,
                    )
                slept = await self._safe_sleep(60, lambda: self.is_custom_rpc)
                if not slept:
                    break
        finally:
            self.is_custom_rpc = False
            self._current_rpc = None
            await self._clear_presence()


async def setup(bot):
    token = bot.config.get("token")
    await bot.add_cog(Presence(bot, token))