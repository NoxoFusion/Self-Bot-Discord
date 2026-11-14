"""
Auto Reactions Cog - Auto react with emojis
- Auto react for a specific user or @everyone (in one channel or all channels)
- Configuration persists to data/state.json ("reactions") across restarts
"""

from typing import Optional, Union
import discord
from discord.ext import commands
import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)
from src.data_store import STATE_FILE, DEFAULTS, load_state, update_state
from src.utils import try_delete

# ── Safety tuning — auto-react là cách nhanh nhất để self-bot bị flag ──
REACT_COOLDOWN_DEFAULT = 3.0    # khoảng cách tối thiểu giữa 2 batch react (giây)
REACT_COOLDOWN_MIN = 1.0
REACT_COOLDOWN_MAX = 30.0
CHANNEL_FORBIDDEN_COOLDOWN = 600.0  # channel thiếu quyền → nghỉ 10 phút
REACT_BACKOFF_MAX = 30.0        # tăng khoảng cách tối đa khi bị rate limit
EMOJI_PER_MESSAGE_CAP = 5       # giới hạn emoji mỗi tin (phòng thủ)


def split_emojis(raw: str) -> list[str]:
    """Split a stored emoji list on commas and/or whitespace.

    Accepts both ``"😂 🙌"`` (dashboard sync format) and ``"😂,🙌"`` (manual
    command input), strips each token and drops empty entries.
    """

    if not raw:
        return []
    return [
        token
        for token in (part.strip() for part in re.split(r"[,\s]+", raw))
        if token
    ]


def _coerce_channel_id(value) -> Optional[int]:
    """Return an int channel id or ``None`` (defensive against dashboard strings)."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else None


class Reactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._user_id: Union[int, str, None] = None   # '@everyone' | user_id | None
        self._auto_react_emojis: Optional[str] = None
        self._auto_react_channel_id: Optional[int] = None
        self.cooldown: float = REACT_COOLDOWN_DEFAULT

        # An toàn: serialize + pacing + circuit breakers (chống flag account)
        self._react_lock = asyncio.Lock()
        self._last_react_at = 0.0
        self._backoff = 1.0
        self._channel_cooldowns: dict = {}   # channel_id -> monotonic nghỉ đến khi
        self._broken_emojis: set = set()      # emoji 400 — loại đến khi đổi list
        self._broken_warned: set = set()      # log 1 lần mỗi emoji chết

        # Khôi phục cấu hình từ state.json
        saved = load_state(STATE_FILE, DEFAULTS).get("reactions", {})
        self._enabled = bool(saved.get("enabled", False))
        if saved.get("user_id") is not None:
            self._user_id = saved["user_id"]
            self.auto_react_emojis = saved.get("emojis")
            self.auto_react_channel_id = saved.get("channel_id")
        self.cooldown = saved.get("cooldown", REACT_COOLDOWN_DEFAULT)

    @property
    def auto_react_emojis(self) -> Optional[str]:
        return self._auto_react_emojis

    @auto_react_emojis.setter
    def auto_react_emojis(self, value) -> None:
        new = str(value) if value is not None else None
        if new != self._auto_react_emojis:
            # Đổi emoji list → reset circuit breaker của từng emoji.
            self._broken_emojis.clear()
            self._broken_warned.clear()
        self._auto_react_emojis = new

    @property
    def auto_react_channel_id(self) -> Optional[int]:
        return self._auto_react_channel_id

    @auto_react_channel_id.setter
    def auto_react_channel_id(self, value) -> None:
        # Sync may hand us a string/empty value — normalise to int | None.
        self._auto_react_channel_id = _coerce_channel_id(value)

    def _cooldown_value(self) -> float:
        """Normalized pacing cooldown (seconds) between reaction batches."""
        try:
            return min(
                REACT_COOLDOWN_MAX,
                max(REACT_COOLDOWN_MIN, float(self.cooldown)),
            )
        except (TypeError, ValueError):
            return REACT_COOLDOWN_DEFAULT

    async def _persist(self):
        """Persist auto-react configuration to state.json."""
        def mutate(state):
            state["reactions"] = {
                "user_id": self._user_id,
                "emojis": self.auto_react_emojis,
                "channel_id": self.auto_react_channel_id,
                "cooldown": self._cooldown_value(),
                "enabled": self._enabled,
            }
        await update_state(STATE_FILE, DEFAULTS, mutate)

    async def convert_to_emoji(self, emoji_str: str) -> Union[discord.Emoji, discord.PartialEmoji, str]:
        """Converts a string to a discord.Emoji/PartialEmoji if it's a custom emoji, else returns the string."""
        if emoji_str.startswith(("<:", "<a:")) and emoji_str.endswith(">"):
            try:
                emoji_id = int(emoji_str.split(":")[-1][:-1])
            except ValueError:
                return emoji_str
            emoji = self.bot.get_emoji(emoji_id)
            if emoji:
                return emoji
            # Không có trong cache → PartialEmoji (reaction format chuẩn 'name:id',
            # kể cả emoji động — raw string '<a:name:id>' sẽ thành 'a:name:id' → Discord 400)
            partial = discord.PartialEmoji.from_str(emoji_str)
            if partial.id is not None:
                return partial
        return emoji_str

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listens for messages and reacts with the auto react emojis if set."""
        if not self._enabled:
            return
        if message.author.id == self.bot.user.id:
            return
        if message.author.bot:  # không react vào tin của bot/webhook khác
            return

        if not (self.auto_react_emojis and self._user_id):
            return

        if self._user_id != "@everyone" and message.author.id != self._user_id:
            return
        if self.auto_react_channel_id and message.channel.id != self.auto_react_channel_id:
            return

        # Channel circuit breaker — bỏ qua channel vừa 403 trong 10 phút.
        if self._channel_cooldowns.get(message.channel.id, 0.0) > time.monotonic():
            return

        # Serialize: 1 batch react tại 1 thời điểm; tin dồn dập thì DROP
        # thay vì xếp hàng (không cho phép bùng nổ API call).
        if self._react_lock.locked():
            return

        async with self._react_lock:
            await self._react_to(message)

    async def _react_to(self, message: discord.Message) -> None:
        """React to one message with pacing, breakers and backoff."""
        emojis = [
            emoji
            for emoji in split_emojis(self.auto_react_emojis)
            if emoji not in self._broken_emojis
        ][:EMOJI_PER_MESSAGE_CAP]
        if not emojis:
            return

        # Pacing toàn cục: giữ khoảng cách tối thiểu giữa các batch (× backoff).
        elapsed = time.monotonic() - self._last_react_at
        wait = max(0.0, self._cooldown_value() * self._backoff - elapsed)
        if wait > 0:
            await asyncio.sleep(wait)

        hit_rate_limit = False
        reacted = False
        for emoji in emojis:
            try:
                emoji_obj = await self.convert_to_emoji(emoji)
                await message.add_reaction(emoji_obj)
                reacted = True
                await asyncio.sleep(0.3)  # Delay nhỏ tránh rate limit
            except discord.Forbidden:
                # Channel thiếu quyền Add Reactions — nghỉ 10 phút, không thử lại.
                self._channel_cooldowns[message.channel.id] = (
                    time.monotonic() + CHANNEL_FORBIDDEN_COOLDOWN
                )
                logger.warning(
                    "AUTO REACT: no Add-Reactions permission in channel %s — "
                    "skipping it for 10 minutes",
                    message.channel.id,
                )
                break
            except discord.HTTPException as e:
                status = getattr(e, "status", None)
                code = getattr(e, "code", None)
                if status == 400 and code == 10014:
                    # Emoji không dùng được ở server này (emoji custom chỉ tồn
                    # tại ở server gốc) — loại khỏi danh sách chạy.
                    self._broken_emojis.add(emoji)
                    if emoji not in self._broken_warned:
                        self._broken_warned.add(emoji)
                        logger.warning(
                            "AUTO REACT: %s is not usable in that server "
                            "(custom emojis only work where they exist) — "
                            "dropped until the emoji list changes",
                            emoji,
                        )
                    continue
                if status == 429:
                    hit_rate_limit = True
                    break
                logger.error("AUTO REACT failed %s: %s", emoji, e)
            except Exception as e:
                logger.error("AUTO REACT error: %s", e)

        if hit_rate_limit:
            self._backoff = min(REACT_BACKOFF_MAX, self._backoff * 2.0)
            logger.warning(
                "AUTO REACT: rate limited — increasing spacing to %.1fs",
                self._backoff,
            )
        elif reacted:
            # Batch sạch thì hạ backoff dần về bình thường.
            self._backoff = max(1.0, self._backoff / 2.0)
        self._last_react_at = time.monotonic()

        # Dọn channel cooldown hết hạn để dict không phình.
        if len(self._channel_cooldowns) > 100:
            now = time.monotonic()
            self._channel_cooldowns = {
                cid: until
                for cid, until in self._channel_cooldowns.items()
                if until > now
            }

    async def _show_status(self, ctx) -> None:
        """Show auto-react status (used by .react status)."""
        if self._enabled and self._user_id:
            if self._user_id == "@everyone":
                user_str = "@everyone"
            else:
                user = self.bot.get_user(self._user_id)
                user_str = str(user) if user else str(self._user_id)
            channel_str = f"#{self.auto_react_channel_id}" if self.auto_react_channel_id else "All channels"
            await ctx.send(
                f"**🎯 Auto React: ✅ Enabled** | 👤 `{user_str}` | 📝 `{channel_str}` | 😀 {self.auto_react_emojis or 'None'}",
                delete_after=10
            )
        else:
            await ctx.send(f"**🎯 Auto React: ❌ Disabled** — `{ctx.prefix}react @user <emojis>`", delete_after=5)

    async def _stop_react(self, ctx) -> None:
        """Disable auto-react (used by .react off)."""
        self._enabled = False
        self._user_id = None
        self.auto_react_emojis = None
        self.auto_react_channel_id = None
        await self._persist()
        await ctx.send("**✅ Auto react disabled**", delete_after=5)

    @commands.command(name='react', aliases=['auto_react'])
    async def react(self, ctx, user: str = None, *, emojis: str = None) -> None:
        """Usage: {prefix}react <@user/all> <emojis> | {prefix}react off | {prefix}react status"""
        await try_delete(ctx.message)

        if user is None or user.lower() == "status":
            return await self._show_status(ctx)
        if user.lower() in ("off", "stop"):
            return await self._stop_react(ctx)
        if not emojis:
            return await ctx.send(
                f"**❌ Usage:** `{ctx.prefix}react @user 🔥 💀` | `{ctx.prefix}react off` | `{ctx.prefix}react status`",
                delete_after=8,
            )

        if user.lower() == "all":
            self._user_id = "@everyone"
            self.auto_react_channel_id = ctx.channel.id
        else:
            try:
                user_obj = await commands.UserConverter().convert(ctx, user)
            except commands.UserNotFound:
                return await ctx.send(f"**❌ User `{user}` not found** — `{ctx.prefix}react @user 🔥 💀`", delete_after=5)
            except Exception as e:
                return await ctx.send(f"**❌ Error:** `{e}`", delete_after=5)
            self._user_id = user_obj.id
            self.auto_react_channel_id = None

        self.auto_react_emojis = emojis
        self._enabled = True
        await self._persist()

        target = "@everyone (this channel)" if self._user_id == "@everyone" else f"`{user}` (all channels)"
        await ctx.send(f"**✅ Auto React Enabled** | 👤 {target} | 😀 {emojis}", delete_after=5)



async def setup(bot):
    await bot.add_cog(Reactions(bot))
