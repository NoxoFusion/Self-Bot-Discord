"""
Auto Automation Cog
Handles automatic keyword responses and smart message broadcasting.
"""

from discord.ext import commands
import asyncio
import logging
import random
import time
from src.data_store import STATE_FILE, DEFAULTS, load_state, update_state
from src.utils import try_delete

logger = logging.getLogger(__name__)

# Time-mode waits are sliced so dashboard edits (mode/channel/value/pool)
# apply within ~10s even during a long cycle.
TIME_WAIT_SLICE_SECONDS = 10.0

class AutoMess(commands.Cog):
    """Automatic response and smart messaging commands."""

    def __init__(self, bot):
        self.bot = bot
        self.data = self._load_data()
        self.data["ar_enabled"] = bool(self.data.get("ar_enabled", False))
        self.auto_mess_task = None
        self._msg_count = 0  # đếm tin người khác gửi (mode=message) — thay cho poll history
        self._last_time_send = None  # monotonic timestamp of the last time-mode send

        # Startup is always OFF: the broadcaster loop only starts when the
        # dashboard enables it (apply_runtime_state) or via the 36auto_mess
        # command. Never auto-resume from the saved state on boot.

    def _load_data(self):
        """Loads automation data from data/state.json."""
        return load_state(STATE_FILE, DEFAULTS).get("auto", {})

    async def _save_data(self):
        """Saves current data to data/state.json (read-modify-write under lock)."""
        import copy
        def mutate(state):
            state["auto"] = copy.deepcopy(self.data)
        await update_state(STATE_FILE, DEFAULTS, mutate)

    def _get_random_message(self):
        """Retrieves a random line from the message pool."""
        try:
            pool = self.data.get("message_pool", [])
            return random.choice(pool) if pool else None
        except Exception:
            return None

    # ==================== 1. AUTO RESPONSE (.ar) ====================

    @commands.command(name='ar')
    async def add_ar(self, ctx, *, trigger_response: str):
        """Usage: {prefix}ar <keyword>, <response>"""
        await try_delete(ctx.message)
        try:
            trigger_word, response = map(str.strip, trigger_response.split(',', 1))
        except Exception:
            return await ctx.send(f"❌ Invalid format. Use: `{ctx.prefix}ar keyword, response`", delete_after=5)

        key = trigger_word.lower()
        auto_responses = self.data.setdefault("auto_responses", {})
        previous_enabled = self.data.get("ar_enabled")
        auto_responses[key] = response
        self.data["ar_enabled"] = True
        try:
            await self._save_data()
        except Exception as e:
            # Roll back the in-memory change so memory matches the failed write.
            auto_responses.pop(key, None)
            self.data["ar_enabled"] = previous_enabled
            logger.error("Failed to save auto-response: %s", e)
            return await ctx.send("❌ Failed to save the auto-response.", delete_after=5)
        await ctx.send(f"✅ Added trigger: `{trigger_word}`", delete_after=5)

    @commands.command(name='ar_list')
    async def list_ar(self, ctx):
        """Usage: {prefix}ar_list"""
        await try_delete(ctx.message)

        ars = self.data.get("auto_responses", {})
        if not ars:
            return await ctx.send("❌ The auto-response list is empty.")

        header = (
            "**📝 ACTIVE AUTO RESPONSES:**"
            if self.data.get("ar_enabled")
            else "**📝 AUTO RESPONSES (disabled):**"
        )
        chunks = []
        current = ""
        for line in (f"• {k}: {v}" for k, v in ars.items()):
            if len(line) > 1900:
                line = line[:1897] + "…"
            if current and len(current) + 1 + len(line) > 1900:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks):
            prefix = f"{header}\n" if index == 0 else ""
            await ctx.send(f"{prefix}```\n{chunk}\n```")

    # ==================== 2. AUTO MESS RANDOM (.auto_mess) ====================

    @commands.command(name='auto_mess')
    async def auto_mess_cmd(self, ctx, status: str, channel_id: int = None, mode: str = "time", value: int = 60):
        """Usage: {prefix}auto_mess <on/off> [channel_id] [mode] [value]"""
        await try_delete(ctx.message)

        status_lower = status.lower()
        if status_lower not in ("on", "off"):
            return await ctx.send(
                f"❌ Status must be `on` or `off` (got: `{status}`)", delete_after=8
            )

        if status_lower == "on":
            if mode.lower() not in ("time", "message"):
                return await ctx.send(f"❌ Mode must be `time` or `message` (got: `{mode}`)", delete_after=8)

            # Nếu không có channel_id thì dùng channel hiện tại
            target_channel_id = channel_id if channel_id else ctx.channel.id

            self.data["auto_mess_config"] = {
                "active": True,
                "mode": mode.lower(),
                "value": value,
                "channel_id": target_channel_id
            }
            self._msg_count = 0
            await self._save_data()

            if self.auto_mess_task:
                self.auto_mess_task.cancel()
                await asyncio.gather(self.auto_mess_task, return_exceptions=True)  # chờ chết hẳn — không gửi thêm tin
            self.auto_mess_task = asyncio.create_task(self._auto_mess_loop())

            await ctx.send(f"✅ **Auto Mess:** ON | <#{target_channel_id}> | mode `{mode}` | value `{value}`", delete_after=10)
        else:
            self.data.setdefault("auto_mess_config", {})["active"] = False
            await self._save_data()
            if self.auto_mess_task:
                self.auto_mess_task.cancel()
                await asyncio.gather(self.auto_mess_task, return_exceptions=True)
                self.auto_mess_task = None
            await ctx.send("❌ **Auto Mess Random:** OFF", delete_after=8)

    def _config_signature(self):
        """Return the broadcaster fields whose change should interrupt a wait."""
        cfg = self.data.get("auto_mess_config", {}) or {}
        return (
            bool(cfg.get("active")),
            cfg.get("mode"),
            cfg.get("channel_id"),
            cfg.get("value"),
        )

    async def _wait_for_next_time_send(self, next_send_at):
        """Wait until ``next_send_at`` in short slices so config edits apply fast.

        Returns ``True`` when the deadline passed with an unchanged config, or
        ``False`` when the broadcaster config changed mid-wait (including being
        disabled) — the caller must re-read it at the top of the loop.
        """
        signature = self._config_signature()
        while True:
            if self._config_signature() != signature:
                return False
            remaining = next_send_at - time.monotonic()
            if remaining <= 0:
                return True
            await asyncio.sleep(min(TIME_WAIT_SLICE_SECONDS, remaining))

    async def _auto_mess_loop(self):
        """Loop for smart random messaging — mode=message counts via listener, no history polling."""
        while self.data.get("auto_mess_config", {}).get("active"):
            config = self.data["auto_mess_config"]
            channel_id = config.get("channel_id")
            if (
                not isinstance(channel_id, int)
                or isinstance(channel_id, bool)
                or channel_id <= 0
            ):
                logger.warning(
                    "Auto-mess active but channel_id is invalid (%r) — "
                    "skipping send cycle",
                    channel_id,
                )
                await asyncio.sleep(30)
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                await asyncio.sleep(10)
                continue

            if config["mode"] == "time":
                try:
                    interval = max(30, int(config.get("value") or 60))
                except (TypeError, ValueError):
                    interval = 60
                now = time.monotonic()
                next_send_at = (
                    now
                    if self._last_time_send is None
                    else self._last_time_send + interval
                )
                if next_send_at > now:
                    if not await self._wait_for_next_time_send(next_send_at):
                        continue  # config changed mid-wait — re-read at the top
                msg = self._get_random_message()
                if msg:
                    try: await channel.send(msg)
                    except Exception as e: logger.debug("Auto-mess send failed (channel %s): %s", channel_id, e)
                self._last_time_send = time.monotonic()
                continue

            elif config["mode"] == "message":
                # _msg_count được tăng bởi listener on_message — 0 API call
                try:
                    value = max(1, int(config.get("value") or 60))
                except (TypeError, ValueError):
                    value = 60
                if self._msg_count >= value:
                    self._msg_count = 0
                    msg = self._get_random_message()
                    if msg:
                        try: await channel.send(msg)
                        except Exception as e: logger.debug("Auto-mess send failed (channel %s): %s", channel_id, e)

                await asyncio.sleep(10)
                continue

            # Lưới an toàn: mode lạ / không nhánh nào chạy vẫn phải ngủ — tránh busy-spin
            await asyncio.sleep(10)

    def cog_unload(self):
        if self.auto_mess_task:
            self.auto_mess_task.cancel()

    # ==================== LISTENER ====================

    @commands.Cog.listener()
    async def on_message(self, message):
        """Keyword auto-responses + message counting for auto_mess mode=message."""
        if message.author.bot: return
        # Self-bot không có bot=True — phải loại riêng tin của chính mình
        # (tránh tự trả lời mình / vòng lặp reply vô hạn)
        if message.author.id == self.bot.user.id: return

        # Đếm tin người khác trong channel đích cho mode=message
        cfg = self.data.get("auto_mess_config", {})
        if (cfg.get("active") and cfg.get("mode") == "message"
                and message.author.id != self.bot.user.id
                and message.channel.id == cfg.get("channel_id")):
            self._msg_count += 1

        # Auto Response Trigger Logic
        content = message.content.lower()
        if self.data.get("ar_enabled") and content in self.data.get("auto_responses", {}):
            try:
                await message.channel.send(self.data["auto_responses"][content])
            except Exception as e:
                logger.debug("Auto-response send failed: %s", e)


async def setup(bot):
    """Cog setup function."""
    await bot.add_cog(AutoMess(bot))