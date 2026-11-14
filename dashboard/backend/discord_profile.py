"""Fetch the signed-in Discord account's public profile.

The dashboard backend runs locally and already has access to the self-bot token
from the repository root ``config.json``.  This module uses that token only to
read ``/users/@me`` and never returns or logs the token itself.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import aiohttp

from .discord_identity import discord_headers

DISCORD_ME_URL = "https://discord.com/api/v10/users/@me"

ProfileFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Discord ``public_flags`` bits exposed on the profile card.
_BADGE_FLAGS: tuple[tuple[int, str, str], ...] = (
    (1 << 0, "staff", "Staff"),
    (1 << 1, "partner", "Partner"),
    (1 << 2, "hypesquad_events", "HypeSquad Events"),
    (1 << 3, "bug_hunter", "Bug Hunter"),
    (1 << 6, "bravery", "Bravery"),
    (1 << 7, "brilliance", "Brilliance"),
    (1 << 8, "balance", "Balance"),
    (1 << 9, "early_supporter", "Early Supporter"),
    (1 << 14, "bug_hunter_gold", "Bug Hunter Gold"),
    (1 << 16, "verified_bot", "Verified Bot"),
    (1 << 17, "early_verified_bot_developer", "Early Verified Bot Dev"),
    (1 << 18, "moderator_alumni", "Moderator Alumni"),
    (1 << 22, "active_developer", "Active Developer"),
)


def _avatar_url(user_id: str, avatar_hash: str | None) -> str:
    if avatar_hash:
        extension = "gif" if avatar_hash.startswith("a_") else "png"
        return (
            f"https://cdn.discordapp.com/avatars/{user_id}/"
            f"{avatar_hash}.{extension}?size=128"
        )

    try:
        index = (int(user_id) >> 22) % 6
    except (TypeError, ValueError):
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def _banner_url(user_id: str, banner_hash: str | None) -> str | None:
    if not banner_hash:
        return None
    extension = "gif" if banner_hash.startswith("a_") else "png"
    return (
        f"https://cdn.discordapp.com/banners/{user_id}/"
        f"{banner_hash}.{extension}?size=600"
    )


def _accent_color(data: dict[str, Any]) -> str | None:
    accent = data.get("accent_color")
    if (
        isinstance(accent, int)
        and not isinstance(accent, bool)
        and 0 <= accent <= 0xFFFFFF
    ):
        return f"#{accent:06X}"

    banner_color = data.get("banner_color")
    if isinstance(banner_color, str):
        color = banner_color.strip()
        if _HEX_COLOR_RE.fullmatch(color):
            return color
    return None


def _created_at(user_id: str) -> str | None:
    try:
        snowflake = int(user_id)
    except (TypeError, ValueError):
        return None
    if snowflake < 0:
        return None

    timestamp_ms = (snowflake >> 22) + 1420070400000
    try:
        return datetime.fromtimestamp(
            timestamp_ms / 1000, tz=timezone.utc
        ).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _premium_type(value: Any) -> int:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 3
    ):
        return value
    return 0


def _badges(public_flags: Any) -> list[dict[str, str]]:
    if not isinstance(public_flags, int) or isinstance(public_flags, bool):
        return []
    return [
        {"id": badge_id, "label": label}
        for bit, badge_id, label in _BADGE_FLAGS
        if public_flags & bit
    ]


def _normalize_profile(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None

    user_id = data.get("id")
    username = data.get("username")
    if not isinstance(user_id, str) or not user_id:
        return None
    if not isinstance(username, str) or not username:
        return None

    display_name = data.get("global_name")
    if not isinstance(display_name, str) or not display_name:
        display_name = username

    avatar_hash = data.get("avatar")
    if not isinstance(avatar_hash, str):
        avatar_hash = None

    banner_hash = data.get("banner")
    if not isinstance(banner_hash, str):
        banner_hash = None

    return {
        "username": username,
        "display_name": display_name,
        "user_id": user_id,
        "avatar_url": _avatar_url(user_id, avatar_hash),
        "banner_url": _banner_url(user_id, banner_hash),
        "accent_color": _accent_color(data),
        "created_at": _created_at(user_id),
        "premium_type": _premium_type(data.get("premium_type")),
        "badges": _badges(data.get("public_flags")),
    }


async def fetch_discord_profile(
    token: str, timeout: float = 5.0
) -> dict[str, Any] | None:
    """Return the profile for ``token`` or ``None`` when it cannot be read."""

    token = token.strip() if isinstance(token, str) else ""
    if not token:
        return None

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            for authorization in (token, f"Bot {token}"):
                async with session.get(
                    DISCORD_ME_URL,
                    headers={
                        "Authorization": authorization,
                        **discord_headers(token),
                    },
                ) as response:
                    if response.status == 200:
                        return _normalize_profile(await response.json())
                    if response.status not in (401, 403):
                        return None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None

    return None


class DiscordProfileService:
    """Small in-memory cache around :func:`fetch_discord_profile`."""

    def __init__(
        self,
        token: str,
        fetcher: ProfileFetcher = fetch_discord_profile,
        ttl: float = 300.0,
        failure_ttl: float = 30.0,
    ) -> None:
        self._token = token.strip() if isinstance(token, str) else ""
        self._fetcher = fetcher
        self._ttl = ttl
        self._failure_ttl = failure_ttl
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._failed_at: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def get(self) -> dict[str, Any] | None:
        if not self._token:
            return None

        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached
        if (
            self._failed_at is not None
            and now - self._failed_at < self._failure_ttl
        ):
            return None

        profile = await self._fetcher(self._token)
        if profile:
            self._cached = profile
            self._cached_at = now
            self._failed_at = None
        else:
            self._failed_at = now
        return profile
