"""
General Commands Cog
Basic utility and information commands for general use.
"""

import discord
from discord.ext import commands
import asyncio
from datetime import datetime

from src.dashboard_sync import get_sync_state
from src.utils import try_delete


class General(commands.Cog):
    """General utility commands for bot and user information."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='clear', aliases=['purge'])
    async def clear_messages(self, ctx, amount: int = 10):
        """Usage: {prefix}clear [amount]"""
        await try_delete(ctx.message)
        
        if amount <= 0:
            return await ctx.send("❌ Amount must be greater than 0.", delete_after=8)
        if amount > 100:
            return await ctx.send("❌ Max 100 messages per purge (rate limit protection).", delete_after=8)

        try:
            deleted = 0
            scanned = 0
            skipped = 0
            before = None  # duyệt theo batch — không bị heuristic limit*2 bỏ sót
            while deleted < amount and scanned < 2000:
                batch = [m async for m in ctx.channel.history(limit=50, before=before)]
                if not batch:
                    break
                before = batch[-1]
                for message in batch:
                    scanned += 1
                    if message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except discord.NotFound:
                            skipped += 1
                            continue
                        except discord.HTTPException:
                            skipped += 1
                            continue
                        deleted += 1
                        await asyncio.sleep(0.5)  # tránh rate limit
                        if deleted >= amount:
                            break

            status_msg = await ctx.send(
                f"{'⚠️' if deleted == 0 else '✅'} Deleted {deleted}/{amount} "
                f"(scanned {scanned}, skipped {skipped})."
            )
            await asyncio.sleep(3)
            try:
                await status_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            
        except discord.Forbidden:
            await ctx.send("❌ Missing permissions to delete messages.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
    
    @commands.command(name='serverinfo', aliases=['srvinfo', 'si'])
    async def server_info(self, ctx):
        """Usage: {prefix}serverinfo"""
        await try_delete(ctx.message)
        
        g = ctx.guild
        if not g:
            return await ctx.send("❌ This command can only be used in a server!", delete_after=10)
        
        created = g.created_at.strftime('%d/%m/%Y %H:%M')
        text_ch = len(g.text_channels)
        voice_ch = len(g.voice_channels)
        categories = len(g.categories)
        roles = len(g.roles) - 1
        emojis = len(g.emojis)
        boosters = g.premium_subscription_count or 0
        boost_level = g.premium_tier

        owner = g.owner
        if owner is None:
            try:
                owner = await g.fetch_member(g.owner_id)
            except (discord.NotFound, discord.Forbidden):
                owner = None

        lines = [
            f"**🏠 SERVER INFO**",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"**Name:** `{g.name}`",
            f"**ID:** `{g.id}`",
            f"**Owner:** {owner.mention if owner else 'N/A'}",
            f"**Created:** `{created}`",
            f"**Members:** `{g.member_count}`",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"**📂 Channels:**",
            f"```",
            f"Text:       {text_ch}",
            f"Voice:      {voice_ch}",
            f"Categories: {categories}",
            f"```",
            f"**⚙️ Other:**",
            f"```",
            f"Roles:       {roles}",
            f"Emojis:      {emojis}",
            f"Boost Level: {boost_level} ({boosters} boosts)",
            f"Verify:      {g.verification_level}",
            f"```",
        ]

        if g.icon:
            lines.append(f"**Icon:** {g.icon.url}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        await ctx.send("\n".join(lines), delete_after=30)
    
    @commands.command(name='userinfo', aliases=['user_info', 'whois', 'ui'])
    async def user_info(self, ctx, user: discord.User = None):
        """Usage: {prefix}userinfo [@user or ID]"""
        await try_delete(ctx.message)
        
        if user is None:
            user = ctx.author
        elif ctx.guild and not isinstance(user, discord.Member):
            found_member = ctx.guild.get_member(user.id)
            if found_member is None:
                try:
                    found_member = await ctx.guild.fetch_member(user.id)
                except (discord.NotFound, discord.Forbidden):
                    found_member = None
            if found_member:
                user = found_member

        created = user.created_at.strftime('%d/%m/%Y %H:%M')

        lines = [
            f"**👤 USER INFO**",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"**ID:** `{user.id}`",
            f"**Username:** `{user.name}`",
            f"**Display:** `{user.display_name}`",
            f"**Bot:** `{user.bot}`",
            f"**Created:** `{created}`",
        ]

        if ctx.guild:
            member = (
                user
                if isinstance(user, discord.Member)
                else ctx.guild.get_member(user.id)
            )
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user.id)
                except (discord.NotFound, discord.Forbidden):
                    member = None
            if member:
                joined = member.joined_at.strftime('%d/%m/%Y %H:%M') if member.joined_at else "N/A"
                roles = [r.name for r in member.roles if r.name != "@everyone"]
                top_role = member.top_role.name if member.top_role.name != "@everyone" else "None"
                lines.append(f"**Joined:** `{joined}`")
                lines.append(f"**Status:** `{member.status}`")
                if member.nick:
                    lines.append(f"**Nickname:** `{member.nick}`")
                lines.append(f"**Top Role:** `{top_role}`")
                lines.append(f"**Roles ({len(roles)}):** {', '.join(roles[:10]) if roles else 'None'}")
                if member.voice:
                    lines.append(f"**Voice:** `{member.voice.channel.name}`")

        avatar_url = user.display_avatar.url

        lines.append(f"**Avatar:** {avatar_url}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        await ctx.send("\n".join(lines), delete_after=30)
    
    @commands.command(name='syncstatus', aliases=['sync_status'])
    async def sync_status(self, ctx):
        """Usage: {prefix}syncstatus — show live dashboard sync state (owner only)"""
        await try_delete(ctx.message)

        afk_cog = self.bot.get_cog("Afk")
        afk_reason = "off"
        if afk_cog is not None and getattr(afk_cog, "afk_enabled", False):
            afk_reason = afk_cog.afk_data.get(str(self.bot.user.id), "off")

        reactions_cog = self.bot.get_cog("Reactions")
        reactions_user = getattr(reactions_cog, "_user_id", None)
        reactions_emojis = getattr(reactions_cog, "auto_react_emojis", None)
        reactions_channel = getattr(reactions_cog, "auto_react_channel_id", None)

        auto_cog = self.bot.get_cog("AutoMess")
        auto_config = auto_cog.data.get("auto_mess_config", {}) if auto_cog else {}

        sync = get_sync_state()
        last_sync = "never"
        if sync.get("last_state_sync"):
            last_sync = datetime.fromtimestamp(
                sync["last_state_sync"]
            ).strftime("%Y-%m-%d %H:%M:%S")
        last_error = sync.get("last_error")
        if last_error and len(str(last_error)) > 200:
            last_error = str(last_error)[:200] + "..."

        lines = [
            "**🔄 SYNC STATUS**",
            f"**AFK:** `{afk_reason}`",
            f"**Reactions:** user=`{reactions_user}` | emojis=`{reactions_emojis}` | channel=`{reactions_channel}`",
            f"**AutoMess:** `{auto_config}`",
            f"**Sync:** last=`{last_sync}` | errors=`{sync.get('sync_errors', 0)}`",
            f"**Last error:** `{last_error}`",
        ]
        await ctx.send("\n".join(lines), delete_after=30)

async def setup(bot):
    """Function to load the cog into the bot."""
    await bot.add_cog(General(bot))