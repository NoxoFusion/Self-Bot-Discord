from __future__ import annotations

import pytest

from dashboard.backend.discord_profile import (
    DiscordProfileService,
    _normalize_profile,
)

pytestmark = pytest.mark.asyncio


async def test_normalize_profile_prefers_global_name():
    profile = _normalize_profile(
        {
            "id": "123456789012345678",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "abc123",
        }
    )

    assert profile == {
        "username": "alice",
        "display_name": "Alice",
        "user_id": "123456789012345678",
        "avatar_url": (
            "https://cdn.discordapp.com/avatars/123456789012345678/"
            "abc123.png?size=128"
        ),
        "banner_url": None,
        "accent_color": None,
        "created_at": "2015-12-07T16:13:12.216000+00:00",
        "premium_type": 0,
        "badges": [],
    }


async def test_normalize_profile_uses_new_default_avatar_index():
    profile = _normalize_profile(
        {
            "id": "1564401778466881618",
            "username": "alice",
            "avatar": None,
        }
    )

    assert profile["avatar_url"].endswith("/embed/avatars/4.png")


async def test_profile_service_caches_result():
    calls = 0

    async def fetcher(token):
        nonlocal calls
        calls += 1
        return {
            "username": "alice",
            "user_id": "123456789012345678",
            "avatar_url": "https://cdn.example/avatar.png",
        }

    service = DiscordProfileService("token", fetcher=fetcher, ttl=60)

    first = await service.get()
    second = await service.get()

    assert first == second
    assert first["username"] == "alice"
    assert calls == 1


async def test_profile_service_without_token_skips_fetcher():
    calls = 0

    async def fetcher(token):
        nonlocal calls
        calls += 1
        return {"username": "alice"}

    service = DiscordProfileService("", fetcher=fetcher)

    assert await service.get() is None
    assert calls == 0


async def test_profile_service_caches_failures_for_failure_ttl():
    calls = 0

    async def fetcher(token):
        nonlocal calls
        calls += 1
        return None

    service = DiscordProfileService(
        "token", fetcher=fetcher, ttl=60, failure_ttl=30
    )

    assert await service.get() is None
    assert await service.get() is None

    assert calls == 1


async def test_profile_service_retries_after_failure_ttl():
    calls = 0

    async def fetcher(token):
        nonlocal calls
        calls += 1
        return None

    service = DiscordProfileService(
        "token", fetcher=fetcher, ttl=60, failure_ttl=0
    )

    assert await service.get() is None
    assert await service.get() is None

    assert calls == 2


async def test_normalize_profile_includes_extended_public_fields():
    profile = _normalize_profile(
        {
            "id": "123456789012345678",
            "username": "alice",
            "banner": "a_bannerhash",
            "accent_color": 0x5865F2,
            "premium_type": 2,
            "public_flags": (1 << 0) | (1 << 9) | (1 << 22),
            "email": "alice@example.com",
            "locale": "en-US",
            "phone": "+15555550100",
            "token": "super-secret-token",
        }
    )

    assert profile["banner_url"] == (
        "https://cdn.discordapp.com/banners/123456789012345678/"
        "a_bannerhash.gif?size=600"
    )
    assert profile["accent_color"] == "#5865F2"
    assert profile["created_at"] == "2015-12-07T16:13:12.216000+00:00"
    assert profile["premium_type"] == 2
    assert profile["badges"] == [
        {"id": "staff", "label": "Staff"},
        {"id": "early_supporter", "label": "Early Supporter"},
        {"id": "active_developer", "label": "Active Developer"},
    ]
    assert "email" not in profile
    assert "locale" not in profile
    assert "phone" not in profile
    assert "token" not in profile
    assert "super-secret-token" not in str(profile)


async def test_normalize_profile_banner_png_and_banner_color_fallback():
    profile = _normalize_profile(
        {
            "id": "123456789012345678",
            "username": "alice",
            "banner": "abc123",
            "banner_color": "#1ABC9C",
        }
    )

    assert profile["banner_url"] == (
        "https://cdn.discordapp.com/banners/123456789012345678/"
        "abc123.png?size=600"
    )
    assert profile["accent_color"] == "#1ABC9C"


async def test_normalize_profile_extended_defaults():
    profile = _normalize_profile(
        {"id": "123456789012345678", "username": "alice"}
    )

    assert profile["banner_url"] is None
    assert profile["accent_color"] is None
    assert profile["premium_type"] == 0
    assert profile["badges"] == []


@pytest.mark.parametrize(
    ("flag", "badge_id", "label"),
    [
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
    ],
)
async def test_normalize_profile_maps_public_flag_badges(flag, badge_id, label):
    profile = _normalize_profile(
        {
            "id": "123456789012345678",
            "username": "alice",
            "public_flags": flag,
        }
    )

    assert profile["badges"] == [{"id": badge_id, "label": label}]
