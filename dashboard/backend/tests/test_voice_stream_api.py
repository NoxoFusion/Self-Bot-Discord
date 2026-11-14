from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import app as backend_app
from dashboard.backend import config as backend_config
from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio

STREAM_PATH = "/api/v1/voice/stream"
CAMERA_PATH = "/api/v1/voice/camera"
TOGGLE_PATHS = [STREAM_PATH, CAMERA_PATH]


class FakeVoiceService:
    def __init__(self):
        self.clear_calls = 0

    async def get_tokens(self):
        return {
            "tokens": [
                {
                    "index": 0,
                    "alive": True,
                    "username": "alice",
                    "display_name": "Alice",
                    "user_id": "1",
                    "avatar_url": None,
                    "error": None,
                }
            ],
            "removed": 0,
        }

    def clear_cache(self):
        self.clear_calls += 1


class FakeVoiceQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


class FakeRequest:
    def __init__(self, app, payload):
        self.app = app
        self.payload = payload

    async def json(self):
        return self.payload


def write_config(path, **overrides):
    data = {
        "token": "root-bot-token",
        "prefix": "!",
        "voice_token": ["existing-token"],
        "nested": {"keep": True},
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    service = FakeVoiceService()
    queue = FakeVoiceQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=service,
        voice_command_queue=queue,
        voice_state_path=tmp_path / "voice_state.json",
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, service, queue


async def test_stream_and_camera_enqueue_commands(api):
    client, _service, queue = api
    csrf = await pair(client)

    response = await client.post(
        STREAM_PATH,
        json={"token_index": 0, "enable": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {"queued": True}

    response = await client.post(
        CAMERA_PATH,
        json={"token_index": 0, "enable": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {"queued": True}

    assert queue.commands == [
        {"action": "stream", "token_index": 0, "enable": True},
        {"action": "camera", "token_index": 0, "enable": True},
    ]


@pytest.mark.parametrize("action", ["stream", "camera"])
async def test_stream_and_camera_return_503_without_queue(app, action):
    request = FakeRequest(app, {"token_index": 0, "enable": True})

    response = await backend_app._post_voice_toggle(request, action)

    assert response.status == 503
    assert json.loads(response.body) == {"error": "voice_unavailable"}


@pytest.mark.parametrize("path", TOGGLE_PATHS)
@pytest.mark.parametrize(
    "payload",
    [
        {"token_index": "0", "enable": True},
        {"token_index": -1, "enable": True},
        {"token_index": 0},
        {"token_index": 0, "enable": "yes"},
        [],
    ],
)
async def test_stream_and_camera_reject_invalid_bodies(api, path, payload):
    client, _service, queue = api
    csrf = await pair(client)

    response = await client.post(
        path,
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


@pytest.mark.parametrize("path", TOGGLE_PATHS)
async def test_stream_and_camera_require_auth_then_csrf(api, path):
    client, _service, queue = api
    payload = {"token_index": 0, "enable": True}

    response = await client.post(path, json=payload)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    await pair(client)
    response = await client.post(path, json=payload)
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    assert queue.commands == []


async def test_get_voice_tokens_merges_stream_flags(api, monkeypatch):
    client, _service, _queue = api

    monkeypatch.setattr(
        backend_app,
        "read_voice_state",
        lambda _path: {
            "updated_at": 1.0,
            "tokens": [
                {
                    "index": 0,
                    "channels": ["456"],
                    "guild_id": "789",
                    "gateway_ready": True,
                    "streaming": True,
                    "video": False,
                }
            ],
        },
    )

    response = await client.get("/api/v1/voice/tokens")

    assert response.status == 200
    body = await response.json()
    token = body["tokens"][0]
    assert token["streaming"] is True
    assert token["video"] is False
    assert token["channels"] == ["456"]
    assert token["guild_id"] == "789"
    assert token["gateway_ready"] is True
