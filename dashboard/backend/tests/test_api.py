from __future__ import annotations

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


def automation_payload(**overrides):
    payload = {
        "enabled": True,
        "triggers": [
            {"keyword": f"keyword-{index}", "reply": f"reply-{index}"}
            for index in range(5)
        ],
        "broadcaster": {
            "enabled": False,
            "mode": "time",
            "value": 60,
            "channel_id": "",
        },
        "pool": ["first message", "second message"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/status",
        "/api/v1/capabilities",
        "/api/v1/automation",
        "/api/v1/afk",
        "/api/v1/reactions",
    ],
)
async def test_read_endpoints_require_a_session(client, path):
    response = await client.get(path)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


async def test_status_contract_has_no_secrets(client):
    await pair(client)

    response = await client.get("/api/v1/status")
    assert response.status == 200
    body = await response.json()

    assert body["bot"] == {
        "state": "offline",
        "username": None,
        "user_id": None,
        "avatar_url": None,
        "latency_ms": None,
        "uptime_seconds": 0,
        "guild_count": 0,
        "last_reload": None,
    }
    assert body["api"]["version"] == "0.1.0"
    assert isinstance(body["api"]["uptime_seconds"], int)
    assert body["features"] == {
        "automation": True,
        "afk": True,
        "reactions": True,
        "voice": True,
        "utility": True,
        "moderation": False,
    }
    assert body["warnings"] == ["Bot token not configured"]
    assert "bot_token" not in body
    assert "token" not in body["bot"]


async def test_status_warns_when_token_is_configured_but_adapter_is_offline(
    tmp_path,
):
    app = create_app(
        config={"bot_token": "super-secret-token"},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        await pair(client)
        response = await client.get("/api/v1/status")
        assert response.status == 200
        text = await response.text()
        body = await response.json()

    assert body["warnings"] == [
        "Live bot adapter not implemented in this build"
    ]
    assert "super-secret-token" not in text


async def test_status_includes_discord_profile_from_service(tmp_path):
    class FakeProfileService:
        async def get(self):
            return {
                "username": "alice",
                "user_id": "123456789012345678",
                "avatar_url": "https://cdn.example/avatar.png",
            }

    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        profile_service=FakeProfileService(),
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        await pair(client)
        response = await client.get("/api/v1/status")
        body = await response.json()

    assert response.status == 200
    assert body["bot"]["username"] == "alice"
    assert body["bot"]["user_id"] == "123456789012345678"
    assert body["bot"]["avatar_url"] == "https://cdn.example/avatar.png"


async def test_capabilities_contract(client):
    await pair(client)

    response = await client.get("/api/v1/capabilities")
    assert response.status == 200
    assert await response.json() == {
        "features": [
            {
                "id": "automation",
                "label": "Auto-Mess",
                "status": "available",
                "reason": "",
            },
            {
                "id": "afk",
                "label": "AFK",
                "status": "available",
                "reason": "",
            },
            {
                "id": "reactions",
                "label": "Auto-Reactions",
                "status": "available",
                "reason": "",
            },
            {
                "id": "voice",
                "label": "Voice",
                "status": "available",
                "reason": "",
            },
            {
                "id": "utility",
                "label": "Utility",
                "status": "available",
                "reason": "",
            },
            {
                "id": "moderation",
                "label": "Moderation",
                "status": "needs_config",
                "reason": "Not implemented in this build",
            },
            {
                "id": "presence",
                "label": "Presence",
                "status": "unsupported",
                "reason": (
                    "User presence spoofing is not supported for "
                    "application bots"
                ),
            },
        ]
    }


async def test_automation_accepts_five_triggers_and_reports_not_applied(
    client,
):
    csrf = await pair(client)
    payload = automation_payload()

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["saved"] is True
    assert body["applied"] is False
    assert body["reason"] == "bot_offline"
    assert body["data"] == payload

    fetched = await client.get("/api/v1/automation")
    assert fetched.status == 200
    assert await fetched.json() == payload


async def test_automation_rejects_six_triggers(client):
    csrf = await pair(client)
    payload = automation_payload(
        triggers=[
            {"keyword": f"keyword-{index}", "reply": f"reply-{index}"}
            for index in range(6)
        ]
    )

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_automation_rejects_six_pool_messages(client):
    csrf = await pair(client)
    payload = automation_payload(
        pool=[f"message {index}" for index in range(6)]
    )

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


@pytest.mark.parametrize(
    "broadcaster",
    [
        {"enabled": True, "mode": "sometimes", "value": 60, "channel_id": ""},
        {"enabled": True, "mode": "time", "value": 29, "channel_id": ""},
        {"enabled": True, "mode": "time", "value": 86401, "channel_id": ""},
        {"enabled": True, "mode": "count", "value": 0, "channel_id": ""},
        {"enabled": True, "mode": "count", "value": 51, "channel_id": ""},
        {"enabled": True, "mode": "time", "value": 60, "channel_id": "abc"},
    ],
)
async def test_automation_rejects_invalid_broadcaster(client, broadcaster):
    csrf = await pair(client)
    payload = automation_payload(broadcaster=broadcaster)

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


@pytest.mark.parametrize(
    "broadcaster",
    [
        {"enabled": True, "mode": "time", "value": 30, "channel_id": ""},
        {"enabled": True, "mode": "time", "value": 86400, "channel_id": ""},
        {"enabled": True, "mode": "message", "value": 1, "channel_id": ""},
        {"enabled": True, "mode": "message", "value": 50, "channel_id": ""},
    ],
)
async def test_automation_accepts_broadcaster_boundaries(client, broadcaster):
    csrf = await pair(client)
    payload = automation_payload(broadcaster=broadcaster)

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["saved"] is True
    assert body["data"]["broadcaster"] == broadcaster


async def test_automation_normalizes_legacy_count_mode(client):
    csrf = await pair(client)
    payload = automation_payload(
        broadcaster={
            "enabled": True,
            "mode": "count",
            "value": 5,
            "channel_id": "",
        }
    )

    response = await client.put(
        "/api/v1/automation",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["data"]["broadcaster"]["mode"] == "message"
    assert body["data"]["broadcaster"]["value"] == 5

    fetched = await client.get("/api/v1/automation")
    assert fetched.status == 200
    assert (await fetched.json())["broadcaster"]["mode"] == "message"


async def test_afk_enabled_without_reason_is_rejected(client):
    csrf = await pair(client)

    response = await client.put(
        "/api/v1/afk",
        json={"enabled": True, "reason": ""},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_afk_valid_put_round_trips(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "reason": "Lunch break",
        "cooldown": 30,
        "reply_mentions": False,
        "reply_dms": True,
    }

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {
        "saved": True,
        "applied": False,
        "reason": "bot_offline",
        "data": payload,
    }

    fetched = await client.get("/api/v1/afk")
    assert fetched.status == 200
    assert await fetched.json() == payload


async def test_afk_defaults_new_fields_when_absent(client):
    csrf = await pair(client)
    payload = {"enabled": True, "reason": "Lunch break"}

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    expected = {
        "enabled": True,
        "reason": "Lunch break",
        "cooldown": 10,
        "reply_mentions": True,
        "reply_dms": True,
    }
    body = await response.json()
    assert body["saved"] is True
    assert body["data"] == expected

    fetched = await client.get("/api/v1/afk")
    assert fetched.status == 200
    assert await fetched.json() == expected


@pytest.mark.parametrize("cooldown", [3, 30, 60])
async def test_afk_accepts_cooldown_in_range(client, cooldown):
    csrf = await pair(client)
    payload = {"enabled": False, "reason": "busy", "cooldown": cooldown}

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["data"]["cooldown"] == cooldown


@pytest.mark.parametrize("cooldown", [2, 61, 0, -5])
async def test_afk_rejects_cooldown_out_of_range(client, cooldown):
    csrf = await pair(client)
    payload = {"enabled": False, "reason": "busy", "cooldown": cooldown}

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "cooldown must be an integer between 3 and 60" in body["details"]


@pytest.mark.parametrize("cooldown", ["10", 1.5, True, None])
async def test_afk_rejects_non_integer_cooldown(client, cooldown):
    csrf = await pair(client)
    payload = {"enabled": False, "reason": "busy", "cooldown": cooldown}

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "cooldown must be an integer between 3 and 60" in body["details"]


@pytest.mark.parametrize("flag", ["reply_mentions", "reply_dms"])
async def test_afk_rejects_non_bool_flags(client, flag):
    csrf = await pair(client)
    payload = {
        "enabled": False,
        "reason": "busy",
        "cooldown": 10,
        flag: "yes",
    }

    response = await client.put(
        "/api/v1/afk",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert f"{flag} must be a boolean" in body["details"]


async def test_reactions_user_target_requires_user_id(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "target": "user",
        "user_id": "",
        "channel_id": "",
        "emojis": ["👍"],
    }

    response = await client.put(
        "/api/v1/reactions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_reactions_valid_put_round_trips(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "target": "user",
        "user_id": "123456789012345678",
        "channel_id": "987654321098765432",
        "emojis": ["👍", "🎉"],
        "cooldown": 3,
    }

    response = await client.put(
        "/api/v1/reactions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {
        "saved": True,
        "applied": False,
        "reason": "bot_offline",
        "data": payload,
    }

    fetched = await client.get("/api/v1/reactions")
    assert fetched.status == 200
    assert await fetched.json() == payload


async def test_reactions_accepts_custom_emoji_round_trip(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "target": "user",
        "user_id": "123456789012345678",
        "channel_id": "",
        "emojis": [
            "<:lamdieu:1547630841172066410>",
            "<a:party:123456789012345678>",
        ],
        "cooldown": 3,
    }

    response = await client.put(
        "/api/v1/reactions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {
        "saved": True,
        "applied": False,
        "reason": "bot_offline",
        "data": payload,
    }

    fetched = await client.get("/api/v1/reactions")
    assert fetched.status == 200
    assert await fetched.json() == payload


async def test_reactions_everyone_requires_channel(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "target": "everyone",
        "user_id": "",
        "channel_id": "",
        "emojis": ["🔥"],
    }

    response = await client.put(
        "/api/v1/reactions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert any("channel_id is required" in detail for detail in body["details"])


async def test_reactions_everyone_with_channel_round_trips(client):
    csrf = await pair(client)
    payload = {
        "enabled": True,
        "target": "everyone",
        "user_id": "",
        "channel_id": "987654321098765432",
        "emojis": ["🔥"],
        "cooldown": 3,
    }

    response = await client.put(
        "/api/v1/reactions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["saved"] is True
    assert body["applied"] is False
    assert body["data"] == payload


async def test_reactions_cooldown_bounds(client):
    csrf = await pair(client)
    base = {
        "enabled": False,
        "target": "user",
        "user_id": "",
        "channel_id": "",
        "emojis": [],
    }

    for bad in (0, 31, "5", True):
        response = await client.put(
            "/api/v1/reactions",
            json={**base, "cooldown": bad},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 400, bad

    for good in (1, 30):
        response = await client.put(
            "/api/v1/reactions",
            json={**base, "cooldown": good},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200, good
        assert (await response.json())["data"]["cooldown"] == good


async def test_utility_weather_returns_current_conditions(client, monkeypatch):
    csrf = await pair(client)
    calls: list[str] = []

    async def fake_fetch_json(url: str, timeout: float = 10.0):
        calls.append(url)
        if "geocoding" in url:
            return 200, {
                "results": [
                    {
                        "name": "Hanoi",
                        "country": "Vietnam",
                        "latitude": 21.03,
                        "longitude": 105.85,
                    }
                ]
            }
        return 200, {
            "current": {
                "temperature_2m": 31.2,
                "apparent_temperature": 35.0,
                "relative_humidity_2m": 70,
                "weather_code": 1,
                "wind_speed_10m": 8.5,
            }
        }

    monkeypatch.setattr(
        "dashboard.backend.utility.fetch_json", fake_fetch_json
    )

    response = await client.post(
        "/api/v1/utility/weather",
        json={"location": "Hanoi"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["ok"] is True
    assert body["data"]["location"] == "Hanoi, Vietnam"
    assert body["data"]["temperature_c"] == 31.2
    assert body["data"]["description"] == "Mainly clear 🌤️"
    assert len(calls) == 2


async def test_utility_weather_rejects_unknown_location(client, monkeypatch):
    csrf = await pair(client)

    async def fake_fetch_json(url: str, timeout: float = 10.0):
        return 200, {"results": []}

    monkeypatch.setattr(
        "dashboard.backend.utility.fetch_json", fake_fetch_json
    )

    response = await client.post(
        "/api/v1/utility/weather",
        json={"location": "Nowhere"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    assert await response.json() == {"error": "location_not_found"}


async def test_utility_weather_maps_network_failure_to_502(
    client, monkeypatch
):
    csrf = await pair(client)
    real_get = aiohttp.ClientSession.get

    def failing_get(session, url, *args, **kwargs):
        if "open-meteo.com" in str(url):
            raise aiohttp.ClientError("network down")
        return real_get(session, url, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "get", failing_get)

    response = await client.post(
        "/api/v1/utility/weather",
        json={"location": "Hanoi"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 502
    assert await response.json() == {"error": "upstream_error"}


async def test_utility_image_returns_keyless_url(client):
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/image",
        json={"prompt": "cat in space"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["ok"] is True
    assert body["data"]["prompt"] == "cat in space"
    assert body["data"]["url"].startswith(
        "https://image.pollinations.ai/prompt/"
    )
    assert "cat%20in%20space" in body["data"]["url"]


async def test_utility_requires_csrf(client):
    await pair(client)

    response = await client.post(
        "/api/v1/utility/image",
        json={"prompt": "cat"},
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}


async def test_utility_emoji_copy_reports_bot_offline(client):
    csrf = await pair(client)
    payload = {
        "source_id": "111111111111111111",
        "target_id": "222222222222222222",
        "emoji_ids": ["333333333333333333", "444444444444444444"],
    }

    response = await client.post(
        "/api/v1/utility/emoji-copy",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["applied"] is False
    assert body["reason"] == "bot_offline"
    assert body["data"] == payload


async def test_utility_clone_requires_confirmation(client):
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/clone",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_utility_clone_reports_bot_offline(client):
    csrf = await pair(client)
    payload = {
        "source_id": "111111111111111111",
        "target_id": "222222222222222222",
        "confirm": True,
    }

    response = await client.post(
        "/api/v1/utility/clone",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert body["applied"] is False
    assert body["reason"] == "bot_offline"
    assert body["data"] == {
        "source_id": "111111111111111111",
        "target_id": "222222222222222222",
        "options": {
            "info": True,
            "structure": True,
            "emojis": False,
        },
    }
