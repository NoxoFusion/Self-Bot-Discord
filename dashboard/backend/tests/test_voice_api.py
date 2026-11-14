from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio


class FakeVoiceService:
    async def get_tokens(self):
        return {
            "tokens": [
                {
                    "index": 0,
                    "alive": True,
                    "username": "alice",
                    "display_name": "Alice",
                    "user_id": "1",
                    "avatar_url": "https://cdn.example/avatar.png",
                    "error": None,
                }
            ],
            "removed": 1,
        }


class FakeSoundboardService:
    def __init__(self):
        self.played = None

    async def list_server_sounds(self, token_index, guild_id):
        return [{"sound_id": "1", "name": "Quack", "emoji_name": "🦆"}]

    async def list_default_sounds(self, token_index):
        return [{"sound_id": "2", "name": "Airhorn"}]

    async def play(self, token_index, channel_id, sound_id, source_guild_id=None):
        self.played = (token_index, channel_id, sound_id, source_guild_id)
        return {"ok": True}


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
async def voice_client(tmp_path):
    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps(
            {
                "updated_at": 123,
                "tokens": [
                    {
                        "index": 0,
                        "gateway_ready": True,
                        "channels": ["456"],
                        "guild_id": "789",
                        "self_mute": False,
                        "self_deaf": True,
                        "guild_channels": {
                            "789": [
                                {"id": "456", "name": "General", "position": 0}
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    soundboard = FakeSoundboardService()
    queue = FakeCommandQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=FakeVoiceService(),
        soundboard_service=soundboard,
        voice_command_queue=queue,
        voice_state_path=state_path,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, soundboard, queue


async def test_voice_tokens_merges_liveness_and_bot_state(voice_client):
    client, _soundboard, _queue = voice_client
    await pair(client)

    response = await client.get("/api/v1/voice/tokens")
    body = await response.json()

    assert response.status == 200
    assert body["removed"] == 1
    assert body["tokens"][0]["username"] == "alice"
    assert body["tokens"][0]["channels"] == ["456"]
    assert body["tokens"][0]["guild_id"] == "789"
    assert body["tokens"][0]["self_mute"] is False
    assert body["tokens"][0]["self_deaf"] is True
    assert body["tokens"][0]["guild_channels"] == {
        "789": [{"id": "456", "name": "General", "position": 0}]
    }
    assert body["state_updated_at"] == 123


async def test_voice_soundboard_lists_and_plays(voice_client):
    client, soundboard, _queue = voice_client
    csrf = await pair(client)

    response = await client.get(
        "/api/v1/voice/soundboard?guild_id=789&token_index=0"
    )
    body = await response.json()
    assert response.status == 200
    assert body["sounds"][0]["name"] == "Quack"

    response = await client.get(
        "/api/v1/voice/soundboard/defaults?token_index=0"
    )
    body = await response.json()
    assert response.status == 200
    assert body["sounds"][0]["name"] == "Airhorn"

    response = await client.post(
        "/api/v1/voice/soundboard/play",
        json={
            "token_index": 0,
            "channel_id": "456",
            "sound_id": "1",
            "source_guild_id": "789",
        },
        headers={"X-CSRF-Token": csrf},
    )
    body = await response.json()
    assert response.status == 200
    assert body == {"ok": True}
    assert soundboard.played == (0, "456", "1", "789")


async def test_voice_join_and_leave_enqueue_commands(voice_client):
    client, _soundboard, queue = voice_client
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/voice/join",
        json={"token_index": 0, "channels": ["456"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert (await response.json()) == {"queued": True}

    response = await client.post(
        "/api/v1/voice/leave",
        json={"token_index": 0, "channel_id": "456"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert (await response.json()) == {"queued": True}

    assert queue.commands == [
        {"action": "join", "token_index": 0, "channels": ["456"]},
        {"action": "leave", "token_index": 0, "channel_id": "456"},
    ]


async def test_voice_soundboard_requires_guild_id(voice_client):
    client, _soundboard, _queue = voice_client
    await pair(client)

    response = await client.get("/api/v1/voice/soundboard?token_index=0")

    assert response.status == 400


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/voice/soundboard?guild_id=789&token_index=0",
        "/api/v1/voice/soundboard/defaults?token_index=0",
    ],
)
async def test_voice_soundboard_gets_require_auth(voice_client, path):
    client, _soundboard, _queue = voice_client

    response = await client.get(path)

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
