"""Dashboard presence actions for the main bot account."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ACTIONS = ["presence_apply", "presence_clear", "presence_reload"]


async def handle(action, command, cog):
    try:
        presence = cog.bot.get_cog("Presence")
    except Exception:
        presence = None
    if presence is None:
        logger.warning("Presence action %r: the Presence cog is not loaded", action)
        return
    try:
        if action in ("presence_apply", "presence_reload"):
            applied = await presence.apply_config()
            if not applied:
                logger.info("Presence apply resulted in no activity (disabled, empty config, or no songs)")
        elif action == "presence_clear":
            await presence.clear_presence()
    except Exception:
        logger.exception("Presence action %r failed", action)
