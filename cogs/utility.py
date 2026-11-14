"""
Utility Commands Cog
Miscellaneous utility tools with built-in English instructions.
"""

from discord.ext import commands, tasks
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

from src.command_spool import drain
from src.http_client import api_request, fetch_bytes
from src.utils import (
    begin_confirm,
    end_confirm,
    is_current_confirm,
    try_delete,
)

logger = logging.getLogger(__name__)

CLONE_COMMANDS_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "clone_commands.json"
)
CLONE_RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "clone_results.json"
)
EMOJI_COMMANDS_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "emoji_commands.json"
)
EMOJI_RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "backend" / "emoji_results.json"
)

CLONE_OPTION_ALIASES = {
    "info": "info",
    "server": "info",
    "server_info": "info",
    "serverinfo": "info",
    "structure": "structure",
    "channels": "structure",
    "categories": "structure",
    "roles": "structure",
    "channels_categories": "structure",
    "channels-categories": "structure",
    "emojis": "emojis",
    "emoji": "emojis",
    "emotes": "emojis",
}


def parse_clone_options(raw):
    """Parse ``.clone`` options into a dict, or ``None`` for invalid input."""

    if raw is None or not str(raw).strip():
        return {"info": True, "structure": True, "emojis": False}

    options = {"info": False, "structure": False, "emojis": False}
    for part in re.split(r"[,\s]+", str(raw).strip().lower()):
        if not part:
            continue
        if part in ("all", "full"):
            return {"info": True, "structure": True, "emojis": True}
        key = CLONE_OPTION_ALIASES.get(part)
        if key is None:
            return None
        options[key] = True

    return options if any(options.values()) else None


def _write_clone_result(request_id, status, message="", **extra):
    """Persist a clone result for the dashboard to poll.

    ``status`` stays one of ``running``/``success``/``error`` so existing
    dashboard pollers keep working. Extra fields (``step``/``done``/``total``/
    ``counts``) are additive and ignored by older clients.
    """

    try:
        data = {}
        if CLONE_RESULTS_PATH.exists():
            try:
                data = json.loads(CLONE_RESULTS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        entry = {
            "status": status,
            "message": message,
            "updated_at": time.time(),
        }
        entry.update({key: value for key, value in extra.items() if value is not None})
        data[request_id] = entry
        CLONE_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CLONE_RESULTS_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(CLONE_RESULTS_PATH)
    except Exception:
        pass


def _format_clone_counts(stats):
    """Build a short ``roles 3/3, channels 12/12`` summary for the result message."""
    parts = []
    for key in ("roles", "categories", "channels", "emojis"):
        total = (stats or {}).get(f"{key}_total", 0)
        if not total:
            continue
        created = (stats or {}).get(f"{key}_created", 0)
        parts.append(f"{key} {created}/{total}")
    return ", ".join(parts)


def _write_emoji_result(request_id, status, message=""):
    """Persist an emoji-copy result for the dashboard to poll."""

    try:
        data = {}
        if EMOJI_RESULTS_PATH.exists():
            try:
                data = json.loads(EMOJI_RESULTS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[request_id] = {
            "status": status,
            "message": message,
            "updated_at": time.time(),
        }
        EMOJI_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = EMOJI_RESULTS_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(EMOJI_RESULTS_PATH)
    except Exception:
        pass

WMO_CODES = {
    0: "Clear sky ☀️", 1: "Mainly clear 🌤️", 2: "Partly cloudy ⛅", 3: "Overcast ☁️",
    45: "Fog 🌫️", 48: "Depositing rime fog 🌫️",
    51: "Light drizzle 🌦️", 53: "Moderate drizzle 🌦️", 55: "Dense drizzle 🌦️",
    56: "Light freezing drizzle 🌧️", 57: "Dense freezing drizzle 🌧️",
    61: "Slight rain 🌧️", 63: "Moderate rain 🌧️", 65: "Heavy rain 🌧️",
    66: "Light freezing rain 🌧️", 67: "Heavy freezing rain 🌧️",
    71: "Slight snow ❄️", 73: "Moderate snow ❄️", 75: "Heavy snow ❄️", 77: "Snow grains ❄️",
    80: "Slight rain showers 🌦️", 81: "Moderate rain showers 🌧️", 82: "Violent rain showers ⛈️",
    85: "Slight snow showers 🌨️", 86: "Heavy snow showers 🌨️",
    95: "Thunderstorm ⛈️", 96: "Thunderstorm with slight hail ⛈️", 99: "Thunderstorm with heavy hail ⛈️",
}

# Import clone module
try:
    from src.clone import CloneHandler, SourceSnapshot, build_source_snapshot
    CLONE_AVAILABLE = True
except ImportError:
    CLONE_AVAILABLE = False
    print("⚠️ Clone module not available")


class Utility(commands.Cog):
    """Utility and miscellaneous commands for daily use."""
    
    def __init__(self, bot):
        self.bot = bot
        self.clone_in_flight = False

    async def cog_load(self):
        if not self._dashboard_clone_commands.is_running():
            self._dashboard_clone_commands.start()
        if not self._dashboard_emoji_commands.is_running():
            self._dashboard_emoji_commands.start()

    def cog_unload(self):
        if self._dashboard_clone_commands.is_running():
            self._dashboard_clone_commands.cancel()
        if self._dashboard_emoji_commands.is_running():
            self._dashboard_emoji_commands.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Restart dashboard loops that a crash-retry left stopped.

        ``cog_load`` runs only once per process, but ``main.py`` retries
        ``bot.run()`` after network crashes. On that retry ``on_ready`` fires
        again while the loops from the previous event loop are dead, so revive
        them here. Each loop is isolated so one failure cannot block the other.
        """

        for name, loop in (
            ("clone", self._dashboard_clone_commands),
            ("emoji", self._dashboard_emoji_commands),
        ):
            try:
                if not loop.is_running():
                    loop.start()
                    logger.info("Restarted dashboard %s command loop", name)
            except Exception:
                logger.exception(
                    "Failed to restart dashboard %s command loop", name
                )

    @tasks.loop(seconds=1)
    async def _dashboard_clone_commands(self):
        """Consume clone requests queued by the local dashboard."""

        for command in drain(CLONE_COMMANDS_PATH):
            if isinstance(command, dict):
                await self._run_dashboard_clone(command)

    async def _prepare_clone_source(self, source_guild, options):
        """Hydrate the source guild and return a snapshot when the cache is partial.

        ``fetch_channels``/``fetch_roles``/``fetch_emojis`` return fresh data but
        do not populate the guild cache, so their results are used directly. If
        the source still has no structure/emoji data, fall back to the REST
        endpoints with the main bot token.
        """
        if not isinstance(options, dict):
            options = {}
        needs_structure = bool(options.get("structure"))
        needs_emojis = bool(options.get("emojis"))
        if not needs_structure and not needs_emojis:
            return None

        roles = list(getattr(source_guild, "roles", []) or [])
        channels = list(getattr(source_guild, "channels", []) or [])
        emojis = list(getattr(source_guild, "emojis", []) or [])

        for label, fetch_name in (
            ("channels", "fetch_channels"),
            ("roles", "fetch_roles"),
            ("emojis", "fetch_emojis"),
        ):
            fetcher = getattr(source_guild, fetch_name, None)
            if fetcher is None:
                continue
            try:
                fetched = await fetcher()
            except Exception as exc:
                logger.warning(
                    "Could not fetch source guild %s (%s): %s",
                    label,
                    getattr(source_guild, "id", "?"),
                    exc,
                )
                continue
            if not fetched:
                continue
            if label == "roles":
                roles = list(fetched)
            elif label == "channels":
                channels = list(fetched)
            else:
                emojis = list(fetched)

        source_roles = [
            role for role in roles if getattr(role, "name", "") != "@everyone"
        ]
        missing_structure = needs_structure and (not source_roles or not channels)
        missing_emojis = needs_emojis and not emojis
        if missing_structure or missing_emojis:
            rest_snapshot = await self._fetch_source_snapshot(source_guild)
            if rest_snapshot is not None:
                return rest_snapshot
            logger.warning(
                "Source guild %s cache is incomplete and the REST fallback failed; "
                "the clone will refuse to delete the target if data is still missing",
                getattr(source_guild, "id", "?"),
            )

        return SourceSnapshot.from_parts(
            roles=roles,
            channels=channels,
            emojis=emojis,
            name=getattr(source_guild, "name", ""),
            guild_id=getattr(source_guild, "id", None),
        )

    async def _fetch_source_snapshot(self, source_guild):
        """Fetch roles/emojis/channels from REST using the main bot token."""
        config = getattr(self.bot, "config", None) or {}
        token = config.get("token")
        if not token:
            logger.warning("Cannot fetch source snapshot: bot token is not configured")
            return None
        token = str(token).strip()
        guild_id = getattr(source_guild, "id", None)
        if guild_id is None:
            return None

        base = "https://discord.com/api/v10"
        status, guild_data = await api_request(
            "GET", f"{base}/guilds/{guild_id}", token=token
        )
        if status != 200 or not isinstance(guild_data, dict):
            logger.warning(
                "Source snapshot guild fetch failed for %s (HTTP %s)",
                guild_id,
                status,
            )
            return None

        status, channel_data = await api_request(
            "GET", f"{base}/guilds/{guild_id}/channels", token=token
        )
        if status != 200 or not isinstance(channel_data, list):
            logger.warning(
                "Source snapshot channel fetch failed for %s (HTTP %s)",
                guild_id,
                status,
            )
            return None

        snapshot = build_source_snapshot(guild_data, channel_data)
        if snapshot is None:
            logger.warning("Source snapshot could not be built for guild %s", guild_id)
            return None
        logger.info(
            "Source snapshot for guild %s: %d roles, %d categories, %d channels, %d emojis",
            guild_id,
            len(snapshot.roles),
            len(snapshot.categories),
            len(snapshot.text_channels) + len(snapshot.voice_channels),
            len(snapshot.emojis),
        )
        return snapshot

    async def _run_dashboard_clone(self, command):
        self.clone_in_flight = True
        try:
            request_id = command.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                return

            try:
                source_id = int(command.get("source_id"))
                target_id = int(command.get("target_id"))
            except (TypeError, ValueError):
                _write_clone_result(request_id, "error", "Invalid guild ID")
                return

            options = command.get("options")
            if not isinstance(options, dict):
                options = {"info": True, "structure": True, "emojis": False}

            if not CLONE_AVAILABLE:
                _write_clone_result(
                    request_id, "error", "Clone module is unavailable"
                )
                return

            source_guild = self.bot.get_guild(source_id)
            target_guild = self.bot.get_guild(target_id)
            if not source_guild or not target_guild:
                _write_clone_result(
                    request_id, "error", "Source or target guild not found"
                )
                return

            _write_clone_result(
                request_id,
                "running",
                "Clone running — paced to avoid Discord account flags "
                "(may take several minutes).",
            )
            try:
                source_snapshot = await self._prepare_clone_source(source_guild, options)
            except Exception as exc:
                logger.warning("Source data preparation failed: %s", exc)
                source_snapshot = None

            progress = {}
            stats = {}

            def report_progress(step, done, total):
                progress.update({"step": step, "done": done, "total": total})
                _write_clone_result(
                    request_id, "running", step, step=step, done=done, total=total
                )

            handler = CloneHandler()
            try:
                success, error = await handler.clone_selective(
                    target_guild,
                    source_guild,
                    options,
                    source_snapshot=source_snapshot,
                    progress=report_progress,
                    stats=stats,
                )
            except asyncio.CancelledError:
                _write_clone_result(request_id, "error", "cancelled", counts=stats)
                raise
            except Exception as exc:
                _write_clone_result(request_id, "error", str(exc), counts=stats)
                return

            if success and not error:
                summary = _format_clone_counts(stats)
                message = "Clone completed"
                if summary:
                    message += f" — {summary}"
                _write_clone_result(
                    request_id, "success", message, **progress, counts=stats
                )
            else:
                _write_clone_result(
                    request_id,
                    "error",
                    error or "Clone failed",
                    **progress,
                    counts=stats,
                )
        finally:
            self.clone_in_flight = False

    @tasks.loop(seconds=1)
    async def _dashboard_emoji_commands(self):
        """Consume emoji-copy requests queued by the local dashboard."""

        for command in drain(EMOJI_COMMANDS_PATH):
            if isinstance(command, dict):
                await self._run_dashboard_emoji_copy(command)

    async def _run_dashboard_emoji_copy(self, command):
        request_id = command.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return

        try:
            source_id = int(command.get("source_id"))
            target_id = int(command.get("target_id"))
        except (TypeError, ValueError):
            _write_emoji_result(request_id, "error", "Invalid guild ID")
            return

        source_guild = self.bot.get_guild(source_id)
        target_guild = self.bot.get_guild(target_id)
        if not source_guild or not target_guild:
            _write_emoji_result(
                request_id, "error", "Source or target guild not found"
            )
            return

        selected, missing, error = self._resolve_emojis(
            source_guild, command.get("emoji_ids")
        )
        if error == "no_matching":
            _write_emoji_result(
                request_id, "error", "No matching emoji IDs found"
            )
            return
        if error == "no_emojis":
            _write_emoji_result(request_id, "error", "Source has no emojis")
            return

        _write_emoji_result(request_id, "running")
        count, failed = await self._copy_emojis(target_guild, selected)

        message = f"Copied {count}/{len(selected)} emojis"
        if failed:
            message += f" · {failed} failed"
        if missing:
            message += f" · {len(missing)} missing"
        status = "success" if count > 0 else "error"
        _write_emoji_result(request_id, status, message)

    @staticmethod
    def _resolve_emojis(source, emoji_ids):
        if emoji_ids:
            try:
                wanted = {int(emoji_id) for emoji_id in emoji_ids}
            except (TypeError, ValueError):
                wanted = set()
            selected = [emoji for emoji in source.emojis if emoji.id in wanted]
            missing = wanted - {emoji.id for emoji in selected}
            if not selected:
                return [], missing, "no_matching"
        else:
            selected = list(source.emojis)
            missing = set()

        if not selected:
            return [], missing, "no_emojis"
        return selected, missing, None

    @staticmethod
    async def _copy_emojis(target, selected):
        count = 0
        failed = 0
        for emoji in selected:
            try:
                image = await fetch_bytes(str(emoji.url))
                if not image:
                    failed += 1
                    continue
                await target.create_custom_emoji(name=emoji.name, image=image)
                count += 1
                await asyncio.sleep(1.5)
            except Exception:
                failed += 1
        return count, failed

    # ==================== WEATHER ====================

    @commands.command(name='weather', aliases=['wth'])
    async def get_weather(self, ctx, *, location: str):
        """Usage: {prefix}weather <city_name | lat,lon>"""
        await try_delete(ctx.message)

        lat, lon, display = await self._resolve_location(location)
        if lat is None:
            return await ctx.send(f"❌ Location `{location}` not found.", delete_after=8)

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
        )
        status, data = await api_request("GET", url, timeout=10)
        current = data.get("current") if isinstance(data, dict) else None
        if status != 200 or not isinstance(current, dict):
            return await ctx.send("❌ Could not reach the weather service.", delete_after=8)

        temp = current.get("temperature_2m")
        feels = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        desc = WMO_CODES.get(current.get("weather_code"), "Unknown")
        await ctx.send(
            f"**🌤️ WEATHER: {display.upper()}**\n"
            f"{desc}\n"
            f"Temperature: **{temp}°C** (feels like {feels}°C)\n"
            f"Humidity: {humidity}% · Wind: {wind} km/h",
            delete_after=15,
        )

    async def _resolve_location(self, location: str):
        """Trả (lat, lon, tên hiển thị) — hỗ trợ nhập trực tiếp 'lat,lon'."""
        m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', location)
        if m:
            return float(m.group(1)), float(m.group(2)), location.strip()
        status, data = await api_request(
            "GET",
            f"https://geocoding-api.open-meteo.com/v1/search?name={quote(location)}&count=1&language=en",
            timeout=10,
        )
        if status != 200 or not isinstance(data, dict):
            return None, None, None
        results = data.get("results") or []
        if not results:
            return None, None, None
        r = results[0]
        display = ", ".join(p for p in (r.get("name"), r.get("country")) if p)
        return r.get("latitude"), r.get("longitude"), display or location

    # ==================== IMAGE GENERATION ====================
    
    @commands.command(name='genimg', aliases=['genimg1', 'draw'])
    async def gen_image_1(self, ctx, *, prompt: str):
        """Usage: {prefix}genimg <description>"""
        await try_delete(ctx.message)
        url = f'https://image.pollinations.ai/prompt/{quote(prompt)}'
        await ctx.send(f"🎨 **AI Generated:** `{prompt}`\n{url}")

    # ==================== EMOJI MANAGEMENT ====================

    @commands.command(name='emoji', aliases=['emoji_copy', 'emoji_add'])
    async def emoji(self, ctx, source_id: int, *emoji_ids: int):
        """{prefix}emoji <source_server_id> [emoji_id...] — copy emojis to the server where you run the command."""
        await try_delete(ctx.message)
        target = ctx.guild
        if target is None:
            return await ctx.send("❌ Use this command inside the target server.", delete_after=8)
        if not ctx.channel.permissions_for(ctx.author).manage_emojis:
            return await ctx.send("❌ You need Manage Emojis permission in this server.", delete_after=8)
        source = self.bot.get_guild(source_id)
        if not source:
            return await ctx.send("❌ Server not found.", delete_after=8)
        if source_id == target.id:
            return await ctx.send("❌ Source and target must be different.", delete_after=8)

        selected, missing, error = self._resolve_emojis(source, emoji_ids)
        if error == "no_matching":
            return await ctx.send(
                f"❌ No matching emoji IDs found in {source.name}: "
                f"{', '.join(map(str, sorted(missing)))}",
                delete_after=10,
            )
        if error == "no_emojis":
            return await ctx.send(
                f"❌ {source.name} has no emojis.", delete_after=8
            )

        total = len(selected)
        await ctx.send(
            f"📤 **Copying {total} emoji(s) → {target.name}...**",
            delete_after=10,
        )
        count, failed = await self._copy_emojis(target, selected)

        msg = f"✅ **Done!** Copied {count}/{total} emojis to {target.name}."
        if emoji_ids:
            names = ", ".join(f"`{e.name}`" for e in selected)
            if len(names) > 400:
                names = names[:400] + "…"
            msg += f"\n🎯 {names}"
        if failed:
            msg += f"\n⚠️ {failed} failed (50 emoji limit / invalid name / over 256KB)."
        if missing:
            msg += f"\n🔍 Missing IDs: {', '.join(map(str, sorted(missing)))}"
        await ctx.send(msg)

    # ==================== SERVER CLONE ====================
    
    @commands.command(name='clone', aliases=['server_clone', 'csrv', 'cloneserver'])
    async def clone_server(self, ctx, source_id: int, target_id: int):
        """{prefix}clone <source_id> <target_id> — copy server info + structure (use the dashboard for section choices)."""
        if not CLONE_AVAILABLE:
            return await ctx.send("❌ Clone module is unavailable!")
        if self.clone_in_flight:
            return await ctx.send("❌ A clone is already running.")

        parsed = parse_clone_options("")

        await try_delete(ctx.message)

        source_guild = self.bot.get_guild(source_id)
        target_guild = self.bot.get_guild(target_id)

        if source_id == target_id:
            return await ctx.send("❌ Source and target must be different servers!", delete_after=8)
        if not source_guild:
            return await ctx.send(f"❌ Source server not found (ID: {source_id})")
        if not target_guild:
            return await ctx.send(f"❌ Target server not found (ID: {target_id})")

        target_member = target_guild.me
        if not target_member:
            return await ctx.send("❌ Bot is not in the target server!")

        required_perms = []
        if parsed["info"]:
            required_perms.append("manage_guild")
        if parsed["structure"]:
            required_perms.extend(["manage_roles", "manage_channels"])
        if parsed["emojis"]:
            required_perms.append("manage_emojis")

        missing_perms = [
            p for p in required_perms
            if not getattr(target_member.guild_permissions, p, False)
        ]
        if missing_perms:
            return await ctx.send(
                f"❌ **Bot is missing permissions in the target server:**\n• {', '.join(missing_perms)}"
            )

        try:
            source_snapshot = await self._prepare_clone_source(source_guild, parsed)
        except Exception as exc:
            logger.warning("Source data preparation failed: %s", exc)
            source_snapshot = None
        source_view = source_snapshot or source_guild
        source_roles = [
            r
            for r in getattr(source_view, "roles", [])
            if getattr(r, "name", "") != "@everyone"
        ]
        source_channels = len(getattr(source_view, "channels", []))
        source_clonable_channels = len(
            getattr(source_view, "text_channels", [])
        ) + len(getattr(source_view, "voice_channels", []))
        if parsed["structure"] and not source_roles and not source_clonable_channels:
            return await ctx.send(
                "❌ Source server has no roles or channels — nothing to clone for structure!"
            )

        options_lines = [
            f"{'✅' if parsed['info'] else '❌'} Server info (name + icon)",
            f"{'✅' if parsed['structure'] else '❌'} Structure (roles + categories + channels)",
            f"{'✅' if parsed['emojis'] else '❌'} Emojis",
        ]
        target_channels = len(target_guild.channels)
        rollback_line = (
            "🔄 A failed structure clone will **automatically roll back**\n\n"
            if parsed["structure"]
            else ""
        )
        # Re-check after the awaits above: two commands can both pass the
        # early check while the other is still preparing its snapshot.
        if self.clone_in_flight:
            return await ctx.send("❌ A clone is already running.")

        self.clone_in_flight = True
        token = begin_confirm(ctx.channel.id)
        try:
            confirm_msg = await ctx.send(
                f"⚠️ **CONFIRM SERVER CLONE**\n"
                f"📤 **Source:** {source_guild.name} ({source_id}) — {len(source_roles)} roles, {source_channels} channels\n"
                f"📥 **Target:** {target_guild.name} ({target_id}) — {target_channels} channels\n\n"
                f"**Selected sections:**\n" + "\n".join(options_lines) + "\n\n"
                f"❗ **Warning:** Enabled sections in the target server will be **DELETED**\n"
                + rollback_line
                + "Type `confirm` within 30 seconds to continue..."
            )

            def check(m):
                return (
                    m.author == ctx.author
                    and m.channel == ctx.channel
                    and m.content.lower() == "confirm"
                    and is_current_confirm(ctx.channel.id, token)
                )

            try:
                await self.bot.wait_for('message', check=check, timeout=30.0)
            except asyncio.TimeoutError:
                return await confirm_msg.edit(content="⏱️ **Timed out - Clone cancelled**")

            await ctx.send("🔄 **Cloning selected sections...**")
            handler = CloneHandler()

            try:
                success, error = await handler.clone_selective(
                    target_guild,
                    source_guild,
                    parsed,
                    source_snapshot=source_snapshot,
                )

                if not error:
                    parts = []
                    if parsed["info"]:
                        parts.append("Server info")
                    if parsed["structure"]:
                        try:
                            fetched = await target_guild.fetch_channels()
                            ch_count = len(fetched)
                        except Exception:
                            ch_count = len(target_guild.channels)
                        roles_count = len(
                            [r for r in target_guild.roles if r.name != "@everyone"]
                        )
                        cat_count = len(target_guild.categories)
                        parts.extend(
                            [
                                f"Roles: {roles_count}",
                                f"Categories: {cat_count}",
                                f"Channels: {ch_count}",
                            ]
                        )
                    if parsed["emojis"]:
                        parts.append(f"Emojis: {len(target_guild.emojis)}")
                    summary = (
                        f"✅ **CLONE COMPLETE!** | 📤 {source_guild.name} → 📥 {target_guild.name}\n"
                        + " · ".join(parts)
                    )
                else:
                    summary = f"❌ **Clone failed**\nError: `{error}`"

                try:
                    first_ch = sorted(target_guild.text_channels, key=lambda c: c.id)
                    target_ch = first_ch[0] if first_ch else ctx.channel
                    await target_ch.send(summary)
                except Exception:
                    try:
                        await ctx.send(summary)
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Clone error: {e}")
                try:
                    await ctx.send(f"❌ **Server clone error:** `{e}`", delete_after=15)
                except Exception:
                    pass
        finally:
            end_confirm(ctx.channel.id, token)
            self.clone_in_flight = False

async def setup(bot):
    await bot.add_cog(Utility(bot))