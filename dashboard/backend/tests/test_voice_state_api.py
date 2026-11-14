from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import config as backend_config
from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio

STATE_PATH = "/api/v1/voice/state"
MOVE_PATH = "/api/v1/voice/move"
CHANNELS_PATH = "/api/v1/voice/channels"


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
async def api(tmp_path, monkeypatch):
    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps(
            {
                "updated_at": 123,
                "guild_channels": {
                    "789": [
                        {"id": "456", "name": "General", "position": 0},
                        {"id": "999", "name": "Gaming", "position": 1},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"voice_token": ["token-0"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)
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
        yield client, queue


@pytest.mark.parametrize("path", [STATE_PATH, MOVE_PATH])
async def test_mutations_require_auth_then_csrf(api, path):
    client, queue = api
    payload = {"token_index": 0, "guild_id": "789", "mute": True}

    response = await client.post(path, json=payload)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    await pair(client)
    response = await client.post(path, json=payload)
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    assert queue.commands == []


async def test_channels_requires_auth(api):
    client, _queue = api

    response = await client.get(
        CHANNELS_PATH, params={"token_index": "0", "guild_id": "789"}
    )

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


@pytest.mark.parametrize(
    "payload",
    [
        {"token_index": 0, "guild_id": "789"},
        {"token_index": 0, "guild_id": "abc", "mute": True},
        {"token_index": 0, "guild_id": "789", "mute": "yes"},
        {"token_index": 0, "guild_id": "789", "deaf": 1},
        {"guild_id": "789", "mute": True},
        {"all": True, "guild_id": "789", "mute": True, "token_index": 0},
        {"all": False, "guild_id": "789", "mute": True},
        {"token_index": "0", "guild_id": "789", "mute": True},
        [],
    ],
)
async def test_state_rejects_invalid_payloads(api, payload):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        STATE_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_state_enqueues_single_token_command(api):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        STATE_PATH,
        json={"token_index": 0, "guild_id": "789", "mute": True},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "voice_state",
            "guild_id": "789",
            "token_index": 0,
            "mute": True,
        }
    ]


async def test_state_enqueues_bulk_command(api):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        STATE_PATH,
        json={"all": True, "guild_id": "789", "deaf": True},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "voice_state",
            "guild_id": "789",
            "all": True,
            "deaf": True,
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"token_index": 0, "guild_id": "789"},
        {"token_index": -1, "guild_id": "789", "channel_id": "999"},
        {"token_index": 0, "guild_id": "abc", "channel_id": "999"},
        {"token_index": 0, "guild_id": "789", "channel_id": "abc"},
        {"token_index": "0", "guild_id": "789", "channel_id": "999"},
        [],
    ],
)
async def test_move_rejects_invalid_payloads(api, payload):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        MOVE_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert queue.commands == []


async def test_move_enqueues_channel_change(api):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        MOVE_PATH,
        json={"token_index": 0, "guild_id": "789", "channel_id": "999"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "move",
            "token_index": 0,
            "guild_id": "789",
            "channel_id": "999",
        }
    ]


async def test_channels_returns_bot_written_cache(api):
    client, _queue = api
    await pair(client)

    response = await client.get(
        CHANNELS_PATH, params={"token_index": "0", "guild_id": "789"}
    )

    assert response.status == 200
    body = await response.json()
    assert body == {
        "channels": [
            {"id": "456", "name": "General", "position": 0},
            {"id": "999", "name": "Gaming", "position": 1},
        ],
        "updated_at": 123,
    }


async def test_move_rejects_unconfigured_token_index(api):
    client, queue = api
    csrf = await pair(client)

    response = await client.post(
        MOVE_PATH,
        json={"token_index": 1, "guild_id": "789", "channel_id": "999"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "token_index is not configured" in body["details"]
    assert queue.commands == []


@pytest.mark.parametrize(
    "params",
    [
        {"guild_id": "789"},
        {"token_index": "0"},
        {"token_index": "-1", "guild_id": "789"},
        {"token_index": "0", "guild_id": "abc"},
        {"token_index": "9" * 5000, "guild_id": "789"},
    ],
)
async def test_channels_rejects_invalid_query(api, params):
    client, _queue = api
    await pair(client)

    response = await client.get(CHANNELS_PATH, params=params)

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"


async def test_state_returns_503_without_command_queue(client):
    csrf = await pair(client)

    response = await client.post(
        STATE_PATH,
        json={"token_index": 0, "guild_id": "789", "mute": True},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 503
    assert await response.json() == {"error": "voice_unavailable"}
