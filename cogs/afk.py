"""
AFK Status Cog
Manages Away-From-Keyboard (AFK) status and automated responses.
"""

import discord
from discord.ext import commands
import time
from src.data_store import STATE_FILE, DEFAULTS, load_state, update_state

class Afk(commands.Cog):
    """Commands to set and manage AFK status."""

    def __init__(self, bot):
        self.bot = bot
        self.afk_data = self._load_data()
        self.afk_enabled = bool(
            load_state(STATE_FILE, DEFAULTS).get("afk_enabled", False)
        )
        self.config = self._load_config()
        self.user_cooldowns = {}

    def _load_data(self):
        """Loads AFK statuses from data/state.json."""
        return load_state(STATE_FILE, DEFAULTS).get("afk", {})

    @staticmethod
    def _normalize_config(raw):
        """Normalize the AFK reply config: cooldown clamped to 3-60 (default 10),
        reply flags default to True when missing or not booleans."""
        merged = dict(DEFAULTS.get("afk_config", {}))
        if isinstance(raw, dict):
            merged.update(raw)

        raw_cooldown = merged.get("cooldown", 10)
        if isinstance(raw_cooldown, bool):
            raw_cooldown = 10
        try:
            cooldown = int(raw_cooldown)
        except (TypeError, ValueError):
            cooldown = 10
        cooldown = max(3, min(60, cooldown))

        reply_mentions = merged.get("reply_mentions", True)
        reply_dms = merged.get("reply_dms", True)
        return {
            "cooldown": cooldown,
            "reply_mentions": reply_mentions if isinstance(reply_mentions, bool) else True,
            "reply_dms": reply_dms if isinstance(reply_dms, bool) else True,
        }

    def _load_config(self):
        """Loads the AFK reply config from data/state.json (merged with defaults)."""
        return self._normalize_config(
            load_state(STATE_FILE, DEFAULTS).get("afk_config", {})
        )

    async def _save_data(self):
        """Saves current AFK statuses to data/state.json (under lock)."""
        def mutate(state):
            state["afk"] = self.afk_data
            state["afk_enabled"] = self.afk_enabled
        await update_state(STATE_FILE, DEFAULTS, mutate)

    async def _clear_afk(self, ctx):
        """Disable AFK — used by .afk off."""
        self.afk_enabled = False
        if str(ctx.author.id) in self.afk_data:
            del self.afk_data[str(ctx.author.id)]
            await self._save_data()

            try:
                await ctx.message.edit(content="✅ **AFK Mode Disabled.** Welcome back!")
            except discord.HTTPException:
                await ctx.send("✅ **AFK Mode Disabled.** Welcome back!")
        else:
            await self._save_data()
            try:
                await ctx.message.edit(content="❌ **You are not currently AFK.**")
            except discord.HTTPException:
                await ctx.send("❌ **You are not currently AFK.**")

    @commands.command(name='afk')
    async def set_afk(self, ctx, *, reason: str = "I am currently busy, will get back to you later."):
        """Usage: {prefix}afk [reason|off] — owner only"""
        if reason.strip().lower() in ("off", "stop"):
            return await self._clear_afk(ctx)

        self.afk_data[str(ctx.author.id)] = reason
        self.afk_enabled = True
        await self._save_data()

        # Edit message instead of delete + send new
        try:
            await ctx.message.edit(content=f"✅ **AFK Mode Enabled:** {reason}")
        except discord.HTTPException:
            # Fallback if edit fails (e.g., message from another user)
            await ctx.send(f"✅ **AFK Mode Enabled:** {reason}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listens for mentions and handles AFK responses."""
        if message.author.bot:
            return

        # Reply when the bot owner is AFK and gets mentioned or DMed
        bot_id = str(self.bot.user.id)
        if self.afk_enabled and bot_id in self.afk_data:
            config = self.config
            is_mentioned = self.bot.user in message.mentions
            is_dm = isinstance(message.channel, discord.DMChannel)

            # Reply only when the configured target type allows it
            should_reply = (
                (is_mentioned and config.get("reply_mentions", True))
                or (is_dm and config.get("reply_dms", True))
            )
            if should_reply and message.author.id != self.bot.user.id:
                # Cooldown theo timestamp — set TRƯỚC khi send để chặn race gửi trùng
                now = time.monotonic()
                last = self.user_cooldowns.get(message.author.id, 0)
                cooldown = config.get("cooldown", 10)
                if now - last >= cooldown:
                    self.user_cooldowns[message.author.id] = now
                    reason = self.afk_data[bot_id]
                    try:
                        await message.channel.send(f"⚠️ **I am currently AFK:** {reason}")
                    except discord.HTTPException:
                        pass
                    # Dọn entry cũ để dict không phình vô hạn
                    if len(self.user_cooldowns) > 100:
                        self.user_cooldowns = {
                            uid: ts for uid, ts in self.user_cooldowns.items() if now - ts < 60
                        }

async def setup(bot):
    """Cog setup function."""
    await bot.add_cog(Afk(bot))