"""
Moderation & Server Management Cog
Commands for server moderation and management
"""

import discord
from discord.ext import commands
import asyncio
import logging
import random

from src.utils import (
    begin_confirm,
    end_confirm,
    is_current_confirm,
    try_delete,
)

logger = logging.getLogger(__name__)

class Moderation(commands.Cog):
    """Moderation and server management commands."""

    def __init__(self, bot):
        self.bot = bot
        self._consecutive_429 = 0

    async def _bulk_paced(self, action, counter: int) -> tuple[bool, bool]:
        """Run one bulk action with random pacing, 429 retry and emergency abort.

        Returns ``(ok, aborted)``. ``aborted`` is True when Discord escalated
        rate limiting (3 consecutive 429s) and the caller must stop.
        """
        await asyncio.sleep(random.uniform(1.2, 2.4))
        if counter > 0 and counter % 10 == 0:
            # Batch pause — same pattern as src/clone.py.
            await asyncio.sleep(random.uniform(3.0, 6.0))

        for attempt in (1, 2):
            try:
                await action()
                self._consecutive_429 = 0
                return True, False
            except discord.HTTPException as e:
                if getattr(e, "status", None) == 429:
                    self._consecutive_429 += 1
                    if self._consecutive_429 >= 3:
                        logger.warning(
                            "[BULK] 3 consecutive 429s — aborting to protect the token"
                        )
                        return False, True
                    if attempt == 1:
                        retry_after = float(getattr(e, "retry_after", None) or 5.0)
                        logger.warning(
                            "[BULK] rate limited — sleeping %.1fs before retrying",
                            retry_after + 0.5,
                        )
                        await asyncio.sleep(retry_after + 0.5)
                        continue
                return False, False
            except Exception:
                return False, False
        return False, False

    # ==================== MODERATION COMMANDS ====================

    @commands.command(name='ban', aliases=['banid'])
    async def ban_by_id(self, ctx, user_id: int, *, reason: str = None):
        """Usage: {prefix}ban <user_id> [reason]"""
        await try_delete(ctx.message)

        if not ctx.guild:
            return await ctx.send("❌ This command can only be used in a server.", delete_after=8)

        if not ctx.channel.permissions_for(ctx.author).ban_members:
            return await ctx.send("❌ You need Ban Members permission in this server.", delete_after=8)
        
        try:
            user = await self.bot.fetch_user(user_id)
            try:
                await ctx.guild.fetch_ban(user)
            except discord.NotFound:
                pass
            else:
                return await ctx.send("❌ That user is already banned.")
            await ctx.guild.ban(user, reason=reason)
            await ctx.send(f"✅ Banned {user.name} (ID: {user_id}) | Reason: {reason or 'None'}")
        except discord.Forbidden:
            await ctx.send("❌ Bot lacks permission to ban.")
        except discord.NotFound:
            await ctx.send("❌ No user found with that ID.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
    
    @commands.command(name='unban')
    async def unban_user(self, ctx, user_id: int):
        """Usage: {prefix}unban <user_id>"""
        await try_delete(ctx.message)

        if not ctx.guild:
            return await ctx.send("❌ This command can only be used in a server.", delete_after=8)

        if not ctx.channel.permissions_for(ctx.author).ban_members:
            return await ctx.send("❌ You need Ban Members permission in this server.", delete_after=8)
        
        try:
            await ctx.guild.unban(discord.Object(id=user_id))
            await ctx.send(f"✅ Unbanned ID: {user_id}")
        except discord.Forbidden:
            await ctx.send("❌ Bot lacks permission to unban.")
        except discord.NotFound:
            await ctx.send("❌ This user is not banned.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
    
    @commands.command(name='nuke')
    @commands.has_permissions(manage_channels=True)
    async def nuke_channel(self, ctx):
        """Usage: {prefix}nuke — recreates this channel; pins, webhooks and invites are lost"""
        if not isinstance(ctx.channel, (discord.TextChannel, discord.VoiceChannel)):
            return await ctx.send("❌ Nuke only works on text/voice channels.")
        if not await self._confirm(
            ctx,
            "⚠️ Nuke this channel? Pins, webhooks and invite links will be lost. "
            "Type `confirm` within 10s.",
        ):
            return
        new_channel = None
        try:
            channel = ctx.channel
            position = channel.position
            category = channel.category
            
            new_channel = await channel.clone()
            await new_channel.edit(position=position, category=category)
            await channel.delete()

            await new_channel.send("💥 **Channel nuked!**")
        except discord.Forbidden:
            # ctx.channel có thể đã bị xóa — ưu tiên gửi vào kênh mới nếu có
            if new_channel:
                try:
                    await new_channel.send("❌ Missing manage channels permission (partial).")
                except Exception:
                    await ctx.send("❌ Bot lacks manage channels permission.")
            else:
                await ctx.send("❌ Bot lacks manage channels permission.")
        except Exception as e:
            if new_channel:
                try:
                    await new_channel.send(f"❌ Error: {e}")
                except Exception:
                    await ctx.send(f"❌ Error: {e}")
            else:
                await ctx.send(f"❌ Error: {e}")
    
    # ==================== ACCOUNT MANAGEMENT ====================

    async def _confirm(self, ctx, prompt: str, word: str = "confirm") -> bool:
        """Wait up to 10s for the owner to type the confirmation word."""
        await ctx.send(prompt, delete_after=12)

        token = begin_confirm(ctx.channel.id)

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.lower() == word
                and is_current_confirm(ctx.channel.id, token)
            )

        try:
            message = await self.bot.wait_for('message', check=check, timeout=10.0)
            await try_delete(message)
            return True
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out — cancelled.", delete_after=8)
            return False
        finally:
            end_confirm(ctx.channel.id, token)

    @commands.command(name='leave_groups', aliases=['leaveallgroups', 'leavegroups'])
    async def leave_all_groups(self, ctx):
        """Usage: {prefix}leave_groups"""
        await try_delete(ctx.message)

        if not await self._confirm(ctx, "⚠️ Leave ALL group DMs? Type `confirm` within 10s."):
            return

        groups = [
            channel
            for channel in list(self.bot.private_channels)
            if isinstance(channel, discord.GroupChannel)
        ]
        if not groups:
            return await ctx.send("ℹ️ **No group channels to leave.**")

        if len(groups) > 10:
            await ctx.send(
                f"⏳ **Leaving {len(groups)} group channels** — "
                f"~{len(groups) * 2}s (paced to protect the token)…"
            )

        self._consecutive_429 = 0
        ok = 0
        failed = 0
        aborted = False
        for index, channel in enumerate(groups):
            success, stop = await self._bulk_paced(channel.leave, index)
            if stop:
                aborted = True
                break
            if success:
                ok += 1
            else:
                failed += 1

        if aborted:
            return await ctx.send(
                f"⚠️ **Stopped to protect the token** — left {ok}/{len(groups)} "
                f"groups before Discord's rate limit escalated. Try again later."
            )
        await ctx.send(
            f"✅ **Left {ok}/{len(groups)} group channels**"
            + (f" — {failed} failed" if failed else "")
        )
    
    @commands.command(name='clear_friends', aliases=['delallfriends', 'delfriends'])
    async def delete_all_friends(self, ctx):
        """Usage: {prefix}clear_friends"""
        await try_delete(ctx.message)
        
        if not await self._confirm(ctx, "⚠️ **Are you sure you want to remove all friends? Type `yes` within 10s.**", word="yes"):
            return
        
        friends = list(self.bot.friends)
        if not friends:
            relationships = await self.bot.fetch_relationships()
            friends = [rel for rel in relationships if rel.type is discord.RelationshipType.friend]

        if not friends:
            return await ctx.send("ℹ️ **No friends to remove.**")

        self._consecutive_429 = 0
        ok = 0
        failed = 0
        aborted = False
        for index, friend in enumerate(friends):
            success, stop = await self._bulk_paced(friend.delete, index)
            if stop:
                aborted = True
                break
            if success:
                ok += 1
            else:
                failed += 1

        if aborted:
            return await ctx.send(
                f"⚠️ **Stopped to protect the token** — removed {ok}/{len(friends)} "
                f"friends before Discord's rate limit escalated. Try again later."
            )
        await ctx.send(
            f"✅ **Removed {ok}/{len(friends)} friends**"
            + (f" — {failed} failed" if failed else "")
        )
    
    @commands.command(name='clear_dms', aliases=['closealldms', 'closedms'])
    async def close_all_dms(self, ctx):
        """Usage: {prefix}clear_dms"""
        await try_delete(ctx.message)

        if not await self._confirm(ctx, "⚠️ Close ALL DMs? Type `confirm` within 10s."):
            return

        current_channel_id = ctx.channel.id  # KHÔNG đóng kênh đang gõ lệnh
        dms = [
            channel
            for channel in list(self.bot.private_channels)
            if isinstance(channel, discord.DMChannel)
            and channel.id != current_channel_id
        ]
        if not dms:
            return await ctx.send("ℹ️ **No DM channels to close.**")

        if len(dms) > 10:
            await ctx.send(
                f"⏳ **Closing {len(dms)} DM channels** — "
                f"~{len(dms) * 2}s (paced to protect the token)…"
            )

        self._consecutive_429 = 0
        ok = 0
        failed = 0
        aborted = False
        for index, channel in enumerate(dms):
            success, stop = await self._bulk_paced(channel.close, index)
            if stop:
                aborted = True
                break
            if success:
                ok += 1
            else:
                failed += 1

        if aborted:
            return await ctx.send(
                f"⚠️ **Stopped to protect the token** — closed {ok}/{len(dms)} "
                f"DMs before Discord's rate limit escalated. Try again later."
            )
        await ctx.send(
            f"✅ **Closed {ok}/{len(dms)} DM channels** (kept this channel)"
            + (f" — {failed} failed" if failed else "")
        )

async def setup(bot):
    """Setup function for cog."""
    await bot.add_cog(Moderation(bot))