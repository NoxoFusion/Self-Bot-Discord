"""Tests for the dashboard presence API extension."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import config as backend_config
from dashboard.backend.app import ADAPTER_KEY, create_app
from dashboard.backend.state_store import StateStore
from dashboard.backend.voice_api import presence as presence_module

pytestmark = pytest.mark.asyncio

CONFIG_PATH = "/api/v1/presence/config"
APPLY_PATH = "/api/v1/presence/apply"
CLEAR_PATH = "/api/v1/presence/clear"
YOUTUBE_RESOLVE_PATH = "/api/v1/presence/youtube/resolve"
UPLOAD_PATH = "/api/v1/presence/upload-image"

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_PNG = base64.b64decode(TINY_PNG_B64)


class FakeQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


class FakeOfflineAdapter:
    def can_queue(self):
        return False


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    queue = FakeQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_command_queue=queue,
    )

    presence_path = (
        Path(config_path).resolve().parent / "data" / "rich_presence.json"
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, queue, presence_path


def _default_config() -> dict:
    return {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [],
    }


def _legacy_config() -> dict:
    return {
        "application_id": "1459720870787547359",
        "type": "listening",
        "platform": "MCK",
        "name": "Ai Mới Là Kẻ Xấu Xa",
        "details": "",
        "state": "",
        "service": "desktop",
        "status": "dnd",
        "duration": 31536000,
        "large_image": "cover",
        "large_text": "",
        "small_image": "",
        "small_text": "",
        "buttons": [{"label": "Bio", "url": "https://bio.example/"}],
    }


def _migrated_legacy_config() -> dict:
    return {
        "enabled": True,
        "mode": "custom",
        "status": "dnd",
        "service": "desktop",
        "activities": [
            {
                "type": "listening",
                "name": "MCK",
                "details": "Ai Mới Là Kẻ Xấu Xa",
                "application_id": "1459720870787547359",
                "large_image": "cover",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
                "show_end": False,
                "end_minutes": 30.0,
                "buttons": [{"label": "Bio", "url": "https://bio.example/"}],
            }
        ],
    }


def _valid_config() -> dict:
    return {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "desktop",
        "activities": [
            {
                "type": "playing",
                "name": "  Test Game  ",
                "details": "  Chapter 1  ",
                "state": "",
                "large_image": "cover",
                "large_text": "Cover",
                "platform": "desktop",
                "show_elapsed": True,
                "elapsed_hours": 2.5,
                "buttons": [
                    {"label": " Site ", "url": "https://example.com"},
                    {"label": "", "url": "https://ignored.example"},
                    {
                        "label": "Second",
                        "url": "https://example.com/2",
                    },
                    {
                        "label": "Third",
                        "url": "https://example.com/3",
                    },
                ],
            }
        ],
    }


def _cleaned_config() -> dict:
    return {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "desktop",
        "activities": [
            {
                "type": "playing",
                "name": "Test Game",
                "details": "Chapter 1",
                "large_image": "cover",
                "large_text": "Cover",
                "platform": "desktop",
                "show_elapsed": True,
                "elapsed_hours": 2.5,
                "buttons": [
                    {"label": "Site", "url": "https://example.com"},
                    {
                        "label": "Second",
                        "url": "https://example.com/2",
                    },
                ],
            }
        ],
    }


async def test_get_presence_config_returns_default_when_missing(api):
    client, _queue, presence_path = api
    await pair(client)

    response = await client.get(CONFIG_PATH)

    assert response.status == 200
    assert await response.json() == {"config": _default_config()}
    assert not presence_path.exists()


async def test_get_presence_config_migrates_legacy_flat_file(api):
    client, _queue, presence_path = api
    presence_path.parent.mkdir(parents=True)
    presence_path.write_text(
        json.dumps(_legacy_config()), encoding="utf-8"
    )
    await pair(client)

    response = await client.get(CONFIG_PATH)

    assert response.status == 200
    assert await response.json() == {"config": _migrated_legacy_config()}


async def test_put_presence_config_writes_single_entry_and_enqueues_reload(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={"config": _valid_config()},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {
        "ok": True,
        "config": _cleaned_config(),
        "queued": True,
    }
    assert (
        json.loads(presence_path.read_text(encoding="utf-8"))
        == _cleaned_config()
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_spotify_config_keeps_activities(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "enabled": True,
                "mode": "spotify",
                "status": "idle",
                "service": "",
                "activities": [{"type": "playing", "name": "ignored"}],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected = {
        "enabled": True,
        "mode": "spotify",
        "status": "idle",
        "service": "",
        "activities": [
            {
                "type": "playing",
                "name": "ignored",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
            }
        ],
    }
    assert response.status == 200
    assert await response.json() == {
        "ok": True,
        "config": expected,
        "queued": True,
    }
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_spotify_accepts_custom_activities(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "spotify",
                "status": "online",
                "service": "",
                "activities": [{"type": "playing", "name": "Test Game"}],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    activity = {
        "type": "playing",
        "name": "Test Game",
        "show_elapsed": True,
        "elapsed_hours": 1.0,
    }
    expected = {
        "enabled": True,
        "mode": "spotify",
        "status": "online",
        "service": "",
        "activities": [activity],
    }
    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["config"] == expected
    assert body["config"]["activities"] == [activity]
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_spotify_rejects_duplicate_activity_types(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "enabled": True,
                "mode": "spotify",
                "status": "online",
                "service": "",
                "activities": [
                    {"type": "playing", "name": "Game One"},
                    {"type": "playing", "name": "Game Two"},
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    message = (
        "activities must use distinct types — Discord displays "
        "only one activity per type"
    )
    assert message in body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


async def test_get_config_spotify_returns_activities(api):
    client, _queue, presence_path = api
    stored = {
        "enabled": True,
        "mode": "spotify",
        "status": "online",
        "service": "",
        "activities": [
            {
                "type": "listening",
                "name": "Test Album",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
                "show_end": False,
                "end_minutes": 30.0,
            }
        ],
    }
    presence_path.parent.mkdir(parents=True)
    presence_path.write_text(json.dumps(stored), encoding="utf-8")
    await pair(client)

    response = await client.get(CONFIG_PATH)

    assert response.status == 200
    body = await response.json()
    assert body["config"]["mode"] == "spotify"
    assert body["config"]["activities"] == stored["activities"]


async def test_put_config_allows_empty_custom_activities(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected = {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [],
    }
    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["config"] == expected
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_allows_distinct_activity_types(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {"type": "playing", "name": "Test Game"},
                    {"type": "listening", "name": "Test Album"},
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected = {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [
            {
                "type": "playing",
                "name": "Test Game",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
            },
            {
                "type": "listening",
                "name": "Test Album",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
                "show_end": False,
                "end_minutes": 30.0,
            },
        ],
    }
    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["config"] == expected
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_keeps_end_time_for_listening(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "listening",
                        "name": "Test Album",
                        "show_end": True,
                        "end_minutes": 45,
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    activity = body["config"]["activities"][0]
    assert activity["show_end"] is True
    assert activity["end_minutes"] == 45.0

    stored = json.loads(presence_path.read_text(encoding="utf-8"))
    stored_activity = stored["activities"][0]
    assert stored_activity["show_end"] is True
    assert stored_activity["end_minutes"] == 45.0
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_clamps_end_minutes(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    cases = ((9999, 1440.0), (0, 1.0), ("abc", 30.0))
    for raw_value, expected in cases:
        response = await client.put(
            CONFIG_PATH,
            json={
                "config": {
                    "mode": "custom",
                    "status": "online",
                    "service": "",
                    "activities": [
                        {
                            "type": "listening",
                            "name": "Test Album",
                            "end_minutes": raw_value,
                        }
                    ],
                }
            },
            headers={"X-CSRF-Token": csrf},
        )

        assert response.status == 200
        body = await response.json()
        activity = body["config"]["activities"][0]
        assert activity["end_minutes"] == expected

        stored = json.loads(presence_path.read_text(encoding="utf-8"))
        assert stored["activities"][0]["end_minutes"] == expected

    assert queue.commands == [{"action": "presence_reload"}] * len(cases)


async def test_put_config_duration_minutes(api):
    client, _queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "watching",
                        "name": "Anime",
                        "duration_minutes": 24,
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    activity = body["config"]["activities"][0]
    assert activity["duration_minutes"] == 24.0

    stored = json.loads(presence_path.read_text(encoding="utf-8"))
    assert stored["activities"][0]["duration_minutes"] == 24.0

    for raw_value, expected in ((9999, 1440.0), (-5, None), ("abc", None)):
        response = await client.put(
            CONFIG_PATH,
            json={
                "config": {
                    "mode": "custom",
                    "status": "online",
                    "service": "",
                    "activities": [
                        {
                            "type": "listening",
                            "name": "Song",
                            "duration_minutes": raw_value,
                        }
                    ],
                }
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200
        body = await response.json()
        cleaned_activity = body["config"]["activities"][0]
        if expected is None:
            assert "duration_minutes" not in cleaned_activity
        else:
            assert cleaned_activity["duration_minutes"] == expected

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "playing",
                        "name": "Game",
                        "duration_minutes": 30,
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    body = await response.json()
    assert "duration_minutes" not in body["config"]["activities"][0]


async def test_put_config_drops_end_time_for_playing(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "playing",
                        "name": "Test Game",
                        "show_end": True,
                        "end_minutes": 10,
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    activity = body["config"]["activities"][0]
    assert "show_end" not in activity
    assert "end_minutes" not in activity

    stored = json.loads(presence_path.read_text(encoding="utf-8"))
    stored_activity = stored["activities"][0]
    assert "show_end" not in stored_activity
    assert "end_minutes" not in stored_activity
    assert queue.commands == [{"action": "presence_reload"}]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "config": {
                "mode": "custom",
                "activities": [
                    {"type": "playing", "name": "a"},
                    {"type": "listening", "name": "a"},
                    {"type": "watching", "name": "a"},
                    {"type": "competing", "name": "a"},
                ],
            }
        },
        {
            "config": {
                "mode": "custom",
                "activities": "not a list",
            }
        },
        {
            "config": {
                "mode": "custom",
                "activities": [{"type": "bogus", "name": "a"}],
            }
        },
        {
            "config": {
                "mode": "custom",
                "status": "bogus",
                "activities": [{"type": "playing", "name": "a"}],
            }
        },
        {
            "config": {
                "mode": "bogus",
                "activities": [{"type": "playing", "name": "a"}],
            }
        },
        {},
        {"config": []},
    ],
)
async def test_put_presence_config_rejects_invalid(api, payload):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_accepts_streaming_with_valid_url(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "streaming",
                        "name": "X",
                        "url": "https://twitch.tv/foo",
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected = {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [
            {
                "type": "streaming",
                "name": "X",
                "url": "https://twitch.tv/foo",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
            }
        ],
    }
    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["config"] == expected
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_rejects_streaming_without_url(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [{"type": "streaming", "name": "X"}],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"] == [
        "activities[0].url must be a Twitch or YouTube URL "
        "for streaming activities"
    ]
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_rejects_streaming_with_invalid_url(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {
                        "type": "streaming",
                        "name": "X",
                        "url": "https://example.com/live",
                    }
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"] == [
        "activities[0].url must be a Twitch or YouTube URL "
        "for streaming activities"
    ]
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_rejects_duplicate_activity_types(api):
    client, queue, presence_path = api
    presence_path.parent.mkdir(parents=True)
    presence_path.write_text(
        json.dumps(_cleaned_config()), encoding="utf-8"
    )
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {"type": "playing", "name": "Game One"},
                    {"type": "playing", "name": "Game Two"},
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    message = (
        "activities must use distinct types — Discord displays "
        "only one activity per type"
    )
    assert message in body["details"]
    assert (
        json.loads(presence_path.read_text(encoding="utf-8"))
        == _cleaned_config()
    )
    assert queue.commands == []


async def test_put_config_allows_duplicate_types_when_disabled(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "enabled": False,
                "mode": "custom",
                "status": "online",
                "service": "",
                "activities": [
                    {"type": "playing", "name": "Game One"},
                    {"type": "playing", "name": "Game Two"},
                ],
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected = {
        "enabled": False,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [
            {
                "type": "playing",
                "name": "Game One",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
            },
            {
                "type": "playing",
                "name": "Game Two",
                "show_elapsed": True,
                "elapsed_hours": 1.0,
            },
        ],
    }
    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["config"] == expected
    assert (
        json.loads(presence_path.read_text(encoding="utf-8")) == expected
    )
    assert queue.commands == [{"action": "presence_reload"}]


async def test_presence_apply_and_clear_enqueue_actions(api):
    client, queue, _presence_path = api
    csrf = await pair(client)

    response = await client.post(
        APPLY_PATH,
        json={"token_index": 2},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [{"action": "presence_apply"}]

    response = await client.post(
        CLEAR_PATH,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "presence_apply"},
        {"action": "presence_clear"},
    ]


async def test_presence_mutations_return_503_when_bot_offline(api):
    client, queue, _presence_path = api
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    for path in (APPLY_PATH, CLEAR_PATH):
        response = await client.post(
            path, headers={"X-CSRF-Token": csrf}
        )
        assert response.status == 503
        assert await response.json() == {"error": "bot_offline"}

    assert queue.commands == []


async def test_put_config_offline_returns_200_and_saves(api):
    client, queue, presence_path = api
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={"config": _valid_config()},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {
        "ok": True,
        "queued": False,
        "config": _cleaned_config(),
    }
    assert (
        json.loads(presence_path.read_text(encoding="utf-8"))
        == _cleaned_config()
    )
    assert queue.commands == []

    for path in (APPLY_PATH, CLEAR_PATH):
        response = await client.post(
            path, headers={"X-CSRF-Token": csrf}
        )
        assert response.status == 503
        assert await response.json() == {"error": "bot_offline"}


async def test_presence_endpoints_require_session_and_csrf(api):
    client, queue, _presence_path = api

    response = await client.get(CONFIG_PATH)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    response = await client.put(
        CONFIG_PATH, json={"config": _valid_config()}
    )
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    for path in (APPLY_PATH, CLEAR_PATH):
        response = await client.post(path)
        assert response.status == 401
        assert await response.json() == {"error": "unauthorized"}

    await pair(client)

    response = await client.put(
        CONFIG_PATH, json={"config": _valid_config()}
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    for path in (APPLY_PATH, CLEAR_PATH):
        response = await client.post(path)
        assert response.status == 403
        assert await response.json() == {"error": "csrf_failed"}

    assert queue.commands == []


async def test_put_config_rejects_lone_surrogate_name(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [{"type": "playing", "name": "\ud800"}]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "activities[0].name contains invalid characters" in body["details"]
    assert not presence_path.exists()
    assert not list(presence_path.parent.glob("*.tmp"))
    assert queue.commands == []


@pytest.mark.parametrize(
    "activity",
    [
        {"type": "playing", "name": "Game", "details": "\ud800"},
        {"type": "playing", "name": "Game", "state": "\ud800"},
        {"type": "playing", "name": "Game", "large_image": "\ud800"},
        {"type": "playing", "name": "Game", "large_text": "\ud800"},
        {"type": "playing", "name": "Game", "small_image": "\ud800"},
        {"type": "playing", "name": "Game", "small_text": "\ud800"},
        {"type": "playing", "name": "Game", "application_id": "\ud800"},
        {
            "type": "playing",
            "name": "Game",
            "buttons": [{"label": "\ud800", "url": "https://x.test"}],
        },
        {
            "type": "playing",
            "name": "Game",
            "buttons": [{"label": "X", "url": "https://x.test/\ud800"}],
        },
        {
            "type": "streaming",
            "name": "Live",
            "url": "https://twitch.tv/\ud800",
        },
    ],
)
async def test_put_config_rejects_surrogate_activity_fields(api, activity):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={"config": {"activities": [activity]}},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert any(
        "contains invalid characters" in detail
        for detail in body["details"]
    )
    assert not presence_path.exists()
    assert queue.commands == []


@pytest.mark.parametrize("field", ["mode", "status", "service"])
async def test_put_config_rejects_surrogate_top_level_fields(api, field):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={"config": {"activities": [], field: "\ud800"}},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert f"{field} contains invalid characters" in body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


@pytest.mark.parametrize(
    ("activity_type", "field"),
    [("playing", "show_elapsed"), ("listening", "show_end")],
)
async def test_put_config_rejects_non_boolean_toggles(
    api, activity_type, field
):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {
                        "type": activity_type,
                        "name": "Test",
                        field: "false",
                    }
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert f"activities[0].{field} must be a boolean" in body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_accepts_boolean_toggles(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {
                        "type": "listening",
                        "name": "Album",
                        "show_elapsed": False,
                        "show_end": True,
                    }
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    activity = body["config"]["activities"][0]
    assert activity["show_elapsed"] is False
    assert activity["show_end"] is True
    assert queue.commands == [{"action": "presence_reload"}]


async def test_put_config_rejects_unknown_service(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={"config": {"service": "samsumg", "activities": []}},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    expected = "service must be one of: " + ", ".join(
        sorted(presence_module.PLATFORMS)
    )
    assert expected in body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


@pytest.mark.parametrize("service", ["xbox", None])
async def test_put_config_accepts_supported_or_absent_service(api, service):
    client, queue, presence_path = api
    csrf = await pair(client)

    config = {"activities": []}
    if service is not None:
        config["service"] = service

    response = await client.put(
        CONFIG_PATH,
        json={"config": config},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["config"]["service"] == (service or "")
    assert queue.commands == [{"action": "presence_reload"}]


async def test_get_config_truncates_stored_activities(api):
    client, _queue, presence_path = api
    stored = {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "desktop",
        "activities": [
            {"type": "playing", "name": "One"},
            {"type": "listening", "name": "Two"},
            {"type": "watching", "name": "Three"},
            {"type": "competing", "name": "Four"},
            {
                "type": "streaming",
                "name": "Five",
                "url": "https://twitch.tv/five",
            },
        ],
    }
    presence_path.parent.mkdir(parents=True)
    presence_path.write_text(json.dumps(stored), encoding="utf-8")
    await pair(client)

    response = await client.get(CONFIG_PATH)

    assert response.status == 200
    body = await response.json()
    activities = body["config"]["activities"]
    assert len(activities) == 3
    assert [activity["name"] for activity in activities] == [
        "One",
        "Two",
        "Three",
    ]


async def test_get_config_preserves_entry_when_activities_invalid(api):
    client, _queue, presence_path = api
    stored = {
        "enabled": False,
        "mode": "spotify",
        "status": "dnd",
        "service": "xbox",
        "activities": [
            {"type": "bogus", "name": "Bad"},
            {"type": "playing"},
        ],
    }
    presence_path.parent.mkdir(parents=True)
    presence_path.write_text(json.dumps(stored), encoding="utf-8")
    await pair(client)

    response = await client.get(CONFIG_PATH)

    assert response.status == 200
    assert await response.json() == {
        "config": {
            "enabled": False,
            "mode": "spotify",
            "status": "dnd",
            "service": "xbox",
            "activities": [],
        }
    }


async def test_put_config_rejects_oversized_streaming_url(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {
                        "type": "streaming",
                        "name": "Live",
                        "url": "https://twitch.tv/" + "a" * 500,
                    }
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert (
        "activities[0].url must be at most 512 characters"
        in body["details"]
    )
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_rejects_oversized_application_id(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {
                        "type": "playing",
                        "name": "Game",
                        "application_id": "1" * 33,
                    }
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert (
        "activities[0].application_id must be at most 32 digits"
        in body["details"]
    )
    assert not presence_path.exists()
    assert queue.commands == []


async def test_put_config_rejects_too_many_activities(api):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {"type": "playing", "name": "One"},
                    {"type": "listening", "name": "Two"},
                    {"type": "watching", "name": "Three"},
                    {"type": "competing", "name": "Four"},
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "activities must contain at most 3 entries" in body["details"]
    assert not presence_path.exists()
    assert queue.commands == []


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube:dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube:dQw4w9WgXcQ"),
        ("youtube:abc12345678", "youtube:abc12345678"),
        ("large_image", "large_image"),
        ("https://example.com/image.png", "https://example.com/image.png"),
    ],
)
async def test_put_config_normalizes_youtube_images(api, image, expected):
    client, queue, presence_path = api
    csrf = await pair(client)

    response = await client.put(
        CONFIG_PATH,
        json={
            "config": {
                "activities": [
                    {
                        "type": "playing",
                        "name": "Game",
                        "large_image": image,
                        "small_image": image,
                    }
                ]
            }
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    activity = body["config"]["activities"][0]
    assert activity["large_image"] == expected
    assert activity["small_image"] == expected

    stored = json.loads(presence_path.read_text(encoding="utf-8"))
    stored_activity = stored["activities"][0]
    assert stored_activity["large_image"] == expected
    assert stored_activity["small_image"] == expected
    assert queue.commands == [{"action": "presence_reload"}]


@pytest.mark.parametrize(
    "value",
    [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
async def test_extract_youtube_id_accepts_supported_forms(value):
    assert presence_module._extract_youtube_id(value) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=too-short",
        None,
    ],
)
async def test_extract_youtube_id_rejects_unsupported_forms(value):
    assert presence_module._extract_youtube_id(value) is None


async def test_youtube_resolve_returns_metadata(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)
    requested = []

    def fake_get_text(url):
        requested.append(url)
        return json.dumps(
            {
                "title": "Never Gonna Give You Up",
                "author_name": "Rick Astley",
            }
        )

    monkeypatch.setattr(presence_module, "_http_get_text", fake_get_text)

    response = await client.post(
        YOUTUBE_RESOLVE_PATH,
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {
        "video": {
            "video_id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "channel": "Rick Astley",
            "image": "youtube:dQw4w9WgXcQ",
        }
    }
    assert requested == [
        "https://noembed.com/embed?url="
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ]


async def test_youtube_resolve_rejects_invalid_url(api):
    client, _queue, _presence_path = api
    csrf = await pair(client)

    response = await client.post(
        YOUTUBE_RESOLVE_PATH,
        json={"url": "https://example.com/watch?v=dQw4w9WgXcQ"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"] == ["url must be a YouTube video URL or ID"]


async def test_youtube_resolve_returns_502_when_fetch_fails(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)

    def fake_get_text(url):
        raise OSError("network down")

    monkeypatch.setattr(presence_module, "_http_get_text", fake_get_text)

    response = await client.post(
        YOUTUBE_RESOLVE_PATH,
        json={"url": "dQw4w9WgXcQ"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 502
    assert await response.json() == {"error": "resolve_failed"}


async def test_upload_image_returns_url_and_caches(api, monkeypatch):
    client, _queue, presence_path = api
    csrf = await pair(client)
    calls = []

    def fake_upload(data, filename):
        calls.append((data, filename))
        return "https://files.catbox.moe/abc123.png"

    monkeypatch.setattr(presence_module, "_upload_to_catbox", fake_upload)

    payload = {"filename": "cover.png", "data": TINY_PNG_B64}
    response = await client.post(
        UPLOAD_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 200
    assert await response.json() == {
        "url": "https://files.catbox.moe/abc123.png"
    }
    assert len(calls) == 1
    assert calls[0] == (TINY_PNG, "cover.png")

    cache_path = presence_path.parent / "upload_cache.json"
    assert cache_path.exists()

    response = await client.post(
        UPLOAD_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 200
    assert await response.json() == {
        "url": "https://files.catbox.moe/abc123.png"
    }
    assert len(calls) == 1


async def test_upload_image_rejects_oversized_payload(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)
    calls = []

    def fake_upload(data, filename):
        calls.append((data, filename))
        return "https://files.catbox.moe/abc123.png"

    monkeypatch.setattr(presence_module, "_upload_to_catbox", fake_upload)

    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * presence_module.UPLOAD_MAX_BYTES
    response = await client.post(
        UPLOAD_PATH,
        json={
            "filename": "big.png",
            "data": base64.b64encode(data).decode("ascii"),
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "upload_too_large"}
    assert calls == []


async def test_upload_image_rejects_unknown_format(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)
    calls = []

    def fake_upload(data, filename):
        calls.append((data, filename))
        return "https://files.catbox.moe/abc123.png"

    monkeypatch.setattr(presence_module, "_upload_to_catbox", fake_upload)

    response = await client.post(
        UPLOAD_PATH,
        json={
            "filename": "not-image.png",
            "data": base64.b64encode(b"not an image").decode("ascii"),
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "invalid_image"}
    assert calls == []


async def test_upload_image_rejects_invalid_base64(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)
    calls = []

    def fake_upload(data, filename):
        calls.append((data, filename))
        return "https://files.catbox.moe/abc123.png"

    monkeypatch.setattr(presence_module, "_upload_to_catbox", fake_upload)

    response = await client.post(
        UPLOAD_PATH,
        json={"filename": "cover.png", "data": "%%%not-base64%%%"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "invalid_image"}
    assert calls == []


async def test_upload_image_returns_502_when_upload_fails(api, monkeypatch):
    client, _queue, _presence_path = api
    csrf = await pair(client)

    monkeypatch.setattr(
        presence_module, "_upload_to_catbox", lambda data, filename: None
    )

    response = await client.post(
        UPLOAD_PATH,
        json={"filename": "cover.png", "data": TINY_PNG_B64},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 502
    assert await response.json() == {"error": "upload_failed"}


async def test_new_presence_endpoints_require_session_and_csrf(api):
    client, queue, _presence_path = api

    for path in (YOUTUBE_RESOLVE_PATH, UPLOAD_PATH):
        response = await client.post(path, json={})
        assert response.status == 401
        assert await response.json() == {"error": "unauthorized"}

    await pair(client)

    for path in (YOUTUBE_RESOLVE_PATH, UPLOAD_PATH):
        response = await client.post(path, json={})
        assert response.status == 403
        assert await response.json() == {"error": "csrf_failed"}

    assert queue.commands == []
