"""Tests for the dashboard Auto-Room API extension."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio

AUTO_ROOM_PATH = "/api/v1/voice/auto-room"
GUILD = "123456789012345678"
LOBBY = "223456789012345678"

STORED_CONFIG = {
    "enabled": True,
    "guild_id": GUILD,
    "lobby_channel_id": LOBBY,
    "leader_count": 3,
}


class FakeCommandQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


@pytest_asyncio.fixture
async def api(tmp_path):
    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps({"updated_at": 123, "auto_room": STORED_CONFIG}),
        encoding="utf-8",
    )
    queue = FakeCommandQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_command_queue=queue,
        voice_state_path=state_path,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, queue, state_path


async def test_get_requires_session(api):
    client, _queue, _state_path = api

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


async def test_put_requires_session(api):
    client, queue, _state_path = api

    response = await client.put(AUTO_ROOM_PATH, json=STORED_CONFIG)

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
    assert queue.commands == []


async def test_get_returns_stored_config(api):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    assert await response.json() == {
        **STORED_CONFIG,
        "manual": [],
        "updated_at": 123,
    }


async def test_get_returns_disabled_default_without_state(api):
    client, _queue, state_path = api
    await pair(client)
    state_path.unlink()

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    assert await response.json() == {
        "enabled": False,
        "guild_id": None,
        "lobby_channel_id": None,
        "leader_count": 1,
        "manual": [],
        "updated_at": None,
    }


async def test_get_returns_normalized_manual_entries(api):
    client, _queue, state_path = api
    await pair(client)
    state_path.write_text(
        json.dumps(
            {
                "updated_at": 123,
                "auto_room": {
                    **STORED_CONFIG,
                    "manual": [
                        {"index": 2, "guild_id": GUILD, "channel_id": LOBBY},
                        {
                            "index": 0,
                            "guild_id": "323456789012345678",
                            "channel_id": "423456789012345678",
                            "extra": "ignored",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    assert await response.json() == {
        **STORED_CONFIG,
        "manual": [
            {"index": 2, "guild_id": GUILD, "channel_id": LOBBY},
            {
                "index": 0,
                "guild_id": "323456789012345678",
                "channel_id": "423456789012345678",
            },
        ],
        "updated_at": 123,
    }


async def test_get_filters_invalid_manual_entries(api):
    client, _queue, state_path = api
    await pair(client)
    valid = {"index": 1, "guild_id": GUILD, "channel_id": LOBBY}
    state_path.write_text(
        json.dumps(
            {
                "updated_at": 123,
                "auto_room": {
                    **STORED_CONFIG,
                    "manual": [
                        valid,
                        "not-a-dict",
                        None,
                        {"index": True, "guild_id": GUILD, "channel_id": LOBBY},
                        {"index": -1, "guild_id": GUILD, "channel_id": LOBBY},
                        {"index": "2", "guild_id": GUILD, "channel_id": LOBBY},
                        {"index": 3, "guild_id": "12345", "channel_id": LOBBY},
                        {
                            "index": 4,
                            "guild_id": GUILD,
                            "channel_id": "not-a-channel",
                        },
                        {
                            "index": 5,
                            "guild_id": 123456789012345678,
                            "channel_id": LOBBY,
                        },
                        {"index": 6, "guild_id": GUILD},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    assert (await response.json())["manual"] == [valid]


@pytest.mark.parametrize(
    "manual",
    [
        pytest.param(None, id="missing"),
        pytest.param("not-a-list", id="string"),
        pytest.param({"index": 0}, id="object"),
        pytest.param(7, id="integer"),
    ],
)
async def test_get_returns_empty_manual_when_missing_or_not_list(api, manual):
    client, _queue, state_path = api
    await pair(client)
    config = dict(STORED_CONFIG)
    if manual is not None:
        config["manual"] = manual
    state_path.write_text(
        json.dumps({"updated_at": 123, "auto_room": config}),
        encoding="utf-8",
    )

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    assert (await response.json())["manual"] == []


async def test_get_caps_manual_entries_at_50(api):
    client, _queue, state_path = api
    await pair(client)
    manual = [
        {"index": index, "guild_id": GUILD, "channel_id": LOBBY}
        for index in range(60)
    ]
    state_path.write_text(
        json.dumps(
            {
                "updated_at": 123,
                "auto_room": {**STORED_CONFIG, "manual": manual},
            }
        ),
        encoding="utf-8",
    )

    response = await client.get(AUTO_ROOM_PATH)

    assert response.status == 200
    body = await response.json()
    assert len(body["manual"]) == 50
    assert body["manual"][0]["index"] == 0
    assert body["manual"][-1]["index"] == 49


@pytest.mark.parametrize(
    "payload",
    [
        {"guild_id": GUILD, "lobby_channel_id": LOBBY, "leader_count": 1},
        {
            "enabled": "yes",
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": 1,
        },
        {
            "enabled": True,
            "guild_id": "12345",
            "lobby_channel_id": LOBBY,
            "leader_count": 1,
        },
        {
            "enabled": True,
            "guild_id": "not-a-guild",
            "lobby_channel_id": LOBBY,
            "leader_count": 1,
        },
        {
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": "12345",
            "leader_count": 1,
        },
        {
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": 0,
        },
        {
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": 6,
        },
        {
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": "2",
        },
        {
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": True,
        },
        [],
    ],
)
async def test_put_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.put(
        AUTO_ROOM_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_put_enqueues_valid_command(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.put(
        AUTO_ROOM_PATH,
        json={
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": 5,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "auto_room",
            "enabled": True,
            "guild_id": GUILD,
            "lobby_channel_id": LOBBY,
            "leader_count": 5,
        }
    ]


async def test_put_returns_503_without_command_queue(tmp_path):
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_command_queue=None,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        csrf = await pair(client)
        response = await client.put(
            AUTO_ROOM_PATH,
            json={
                "enabled": True,
                "guild_id": GUILD,
                "lobby_channel_id": LOBBY,
                "leader_count": 1,
            },
            headers={"X-CSRF-Token": csrf},
        )
        body = await response.json()

    assert response.status == 503
    assert body == {"error": "voice_unavailable"}
