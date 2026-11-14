"""Tests for the dashboard audio playback API extension."""

from __future__ import annotations

import json
import time

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import config as backend_config
from dashboard.backend.app import ADAPTER_KEY, create_app
from dashboard.backend.state_store import StateStore
from dashboard.backend.voice_api import media

pytestmark = pytest.mark.asyncio

JOIN_PATH = "/api/v1/voice/join"
PLAY_PATH = "/api/v1/voice/play"
SEARCH_PATH = "/api/v1/voice/search"
STOP_PATH = "/api/v1/voice/audio/stop"
SKIP_PATH = "/api/v1/voice/audio/skip"
LOOP_PATH = "/api/v1/voice/audio/loop"
REPLAY_PATH = "/api/v1/voice/audio/replay"
QUEUE_PATH = "/api/v1/voice/audio/queue"
FILTERS_PATH = "/api/v1/voice/audio/filters"
VOLUME_PATH = "/api/v1/voice/audio/volume"
FORCEFIX_PATH = "/api/v1/voice/audio/forcefix"

GUILD = "123456789012345678"
CHANNEL = "223456789012345678"

STORED_AUDIO = {"0": {"playing": True, "title": "x"}}

FILTER_KEYS = [
    "bass",
    "soft",
    "lofi",
    "slowed reverb",
    "reverb",
    "sped up",
    "dolby",
    "8d",
    "concert",
    "instrumental",
]


class FakeCommandQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


class FakeOfflineAdapter:
    def can_queue(self):
        return False


class RaisingAdapter:
    def can_queue(self):
        raise RuntimeError("liveness probe failed")


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps({"updated_at": 123, "audio": STORED_AUDIO}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"voice_token": ["token-0", "token-1", "token-2"]}),
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
        yield client, queue, state_path


def _play_payload(**overrides):
    payload = {
        "token_index": 0,
        "guild_id": GUILD,
        "channel_id": CHANNEL,
        "query": "lofi beats",
    }
    payload.update(overrides)
    return payload


async def test_play_requires_session(api):
    client, queue, _state_path = api

    response = await client.post(PLAY_PATH, json=_play_payload())

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
    assert queue.commands == []


async def test_queue_requires_session(api):
    client, _queue, _state_path = api

    response = await client.get(QUEUE_PATH, params={"token_index": "0"})

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


@pytest.mark.parametrize(
    "path", [STOP_PATH, SKIP_PATH, LOOP_PATH, REPLAY_PATH, FORCEFIX_PATH]
)
async def test_audio_control_requires_session(api, path):
    client, queue, _state_path = api

    response = await client.post(path, json={"token_index": 0})

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
    assert queue.commands == []


@pytest.mark.parametrize(
    "payload",
    [
        {"guild_id": GUILD, "channel_id": CHANNEL, "query": "lofi"},
        _play_payload(token_index="0"),
        _play_payload(token_index=-1),
        _play_payload(token_index=True),
        _play_payload(guild_id="12345"),
        _play_payload(guild_id="not-a-guild"),
        _play_payload(guild_id="123456789012345678901"),
        _play_payload(channel_id="12345"),
        _play_payload(channel_id="not-a-channel"),
        _play_payload(query=""),
        _play_payload(query="   "),
        _play_payload(query="x" * 301),
        _play_payload(query=123),
        [],
    ],
)
async def test_play_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_play_enqueues_valid_command(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH,
        json=_play_payload(token_index=1, query="  lofi beats  "),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "play",
            "token_index": 1,
            "guild_id": GUILD,
            "channel_id": CHANNEL,
            "query": "lofi beats",
        }
    ]


@pytest.mark.parametrize("overrides", [{}, {"guild_id": ""}])
async def test_play_enqueues_without_guild_id(api, overrides):
    client, queue, _state_path = api
    csrf = await pair(client)
    payload = _play_payload(token_index=2, query="  lofi beats  ")
    payload.pop("guild_id")
    payload.update(overrides)

    response = await client.post(
        PLAY_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "play",
            "token_index": 2,
            "guild_id": "",
            "channel_id": CHANNEL,
            "query": "lofi beats",
        }
    ]


async def test_play_rejects_invalid_nonempty_guild_id(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH,
        json=_play_payload(guild_id="not-a-guild"),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


requires_search = pytest.mark.skipif(
    media.yt_dlp is None
    or media.normalize_query is None
    or media.rank_entries is None,
    reason="voice search dependencies are unavailable",
)


@requires_search
async def test_search_returns_ranked_results(api, monkeypatch):
    client, _queue, _state_path = api
    csrf = await pair(client)

    class FakeYoutubeDL:
        last_options = None
        last_query = None

        def __init__(self, options):
            type(self).last_options = options

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def extract_info(self, query, download=False):
            type(self).last_query = query
            assert download is False
            return {
                "entries": [
                    {
                        "id": "aaaaaaaaaaa",
                        "title": "Lofi Beats",
                        "uploader": "Lofi Music",
                        "duration": 200,
                    },
                    {
                        "id": "bbbbbbbbbbb",
                        "title": "Lofi Beats Official Audio",
                        "uploader": "Lofi Records",
                        "duration": 215,
                        "webpage_url": (
                            "https://www.youtube.com/watch?v=bbbbbbbbbbb"
                        ),
                    },
                    {
                        "id": "ccccccccccc",
                        "title": "Random live stream",
                        "uploader": "Random",
                        "duration": None,
                        "is_live": True,
                    },
                    {
                        "title": "Missing url",
                        "uploader": "Nobody",
                        "duration": 100,
                    },
                    {
                        "id": "ddddddddddd",
                        "uploader": "No Title",
                        "duration": 100,
                    },
                ]
            }

    monkeypatch.setattr(media.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    response = await client.post(
        SEARCH_PATH,
        json={"query": "  lofi beats  "},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    results = (await response.json())["results"]
    assert len(results) == 3
    assert results[0] == {
        "title": "Lofi Beats Official Audio",
        "uploader": "Lofi Records",
        "duration": 215,
        "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    }
    assert results[1] == {
        "title": "Lofi Beats",
        "uploader": "Lofi Music",
        "duration": 200,
        "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
    }
    assert results[2] == {
        "title": "Random live stream",
        "uploader": "Random",
        "duration": None,
        "url": "https://www.youtube.com/watch?v=ccccccccccc",
    }
    assert FakeYoutubeDL.last_query == "ytsearch10:lofi beats"
    assert FakeYoutubeDL.last_options == {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 301},
        {"query": 123},
        [],
    ],
)
async def test_search_rejects_invalid_payloads(api, payload):
    client, _queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        SEARCH_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


@requires_search
async def test_search_returns_502_when_ytdlp_fails(api, monkeypatch):
    client, _queue, _state_path = api
    csrf = await pair(client)

    def fail(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(media.yt_dlp, "YoutubeDL", fail)

    response = await client.post(
        SEARCH_PATH, json={"query": "lofi"}, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 502
    body = await response.json()
    assert body["error"] == "search_failed"
    assert body["message"]
    assert "network down" not in body["message"]


async def test_search_requires_session(api):
    client, _queue, _state_path = api

    response = await client.post(SEARCH_PATH, json={"query": "lofi"})

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


async def test_search_requires_csrf(api):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.post(SEARCH_PATH, json={"query": "lofi"})

    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}


async def test_search_returns_503_without_audio_search(api, monkeypatch):
    client, _queue, _state_path = api
    csrf = await pair(client)
    monkeypatch.setattr(media, "normalize_query", None)
    monkeypatch.setattr(media, "rank_entries", None)

    response = await client.post(
        SEARCH_PATH, json={"query": "lofi"}, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 503
    assert await response.json() == {"error": "search_unavailable"}


@pytest.mark.parametrize(
    ("path", "action"),
    [(STOP_PATH, "audio_stop"), (SKIP_PATH, "audio_skip")],
)
async def test_audio_control_enqueues_command(api, path, action):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        path, json={"token_index": 2}, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [{"action": action, "token_index": 2}]


@pytest.mark.parametrize("path", [STOP_PATH, SKIP_PATH])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0"},
        {"token_index": -1},
        {"token_index": True},
        [],
    ],
)
async def test_audio_control_rejects_invalid_payloads(api, path, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        path, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


@pytest.mark.parametrize("mode", ["off", "track", "queue"])
async def test_audio_loop_enqueues_command(api, mode):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        LOOP_PATH,
        json={"token_index": 2, "mode": mode},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_loop", "token_index": 2, "mode": mode}
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0", "mode": "track"},
        {"token_index": -1, "mode": "track"},
        {"token_index": True, "mode": "track"},
        {"token_index": 0},
        {"token_index": 0, "mode": "bogus"},
        {"token_index": 0, "mode": None},
        {"token_index": 0, "mode": 1},
        [],
    ],
)
async def test_audio_loop_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        LOOP_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_audio_replay_enqueues_command(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        REPLAY_PATH,
        json={"token_index": 2},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [{"action": "audio_replay", "token_index": 2}]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0"},
        {"token_index": -1},
        {"token_index": True},
        [],
    ],
)
async def test_audio_replay_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        REPLAY_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_audio_forcefix_enqueues_command(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FORCEFIX_PATH, json={"token_index": 2}, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_forcefix", "token_index": 2}
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0"},
        {"token_index": -1},
        {"token_index": True},
        [],
    ],
)
async def test_audio_forcefix_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FORCEFIX_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


async def test_audio_filters_enqueues_command(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FILTERS_PATH,
        json={"token_index": 1, "filters": ["bass", "lofi"], "bass_level": 250},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {
            "action": "audio_filters",
            "token_index": 1,
            "filters": ["bass", "lofi"],
            "bass_level": 250,
        }
    ]


async def test_audio_filters_omits_bass_level_when_absent(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FILTERS_PATH,
        json={"token_index": 0, "filters": ["soft"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_filters", "token_index": 0, "filters": ["soft"]}
    ]


async def test_audio_filters_accepts_empty_filter_list(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FILTERS_PATH,
        json={"token_index": 0, "filters": []},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_filters", "token_index": 0, "filters": []}
    ]


async def test_audio_filters_accepts_all_supported_keys(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FILTERS_PATH,
        json={"token_index": 0, "filters": FILTER_KEYS},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_filters", "token_index": 0, "filters": FILTER_KEYS}
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0", "filters": []},
        {"token_index": -1, "filters": []},
        {"token_index": True, "filters": []},
        {"token_index": 0},
        {"token_index": 0, "filters": "bass"},
        {"token_index": 0, "filters": [123]},
        {"token_index": 0, "filters": ["unknown"]},
        {"token_index": 0, "filters": FILTER_KEYS + ["bass"]},
        {"token_index": 0, "filters": [], "bass_level": 0},
        {"token_index": 0, "filters": [], "bass_level": 1000},
        {"token_index": 0, "filters": [], "bass_level": "100"},
        {"token_index": 0, "filters": [], "bass_level": True},
        [],
    ],
)
async def test_audio_filters_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        FILTERS_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


@pytest.mark.parametrize("volume", [0, 50, 200])
async def test_audio_volume_enqueues_command(api, volume):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        VOLUME_PATH,
        json={"token_index": 2, "volume": volume},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"queued": True}
    assert queue.commands == [
        {"action": "audio_volume", "token_index": 2, "volume": volume}
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_index": "0", "volume": 50},
        {"token_index": -1, "volume": 50},
        {"token_index": True, "volume": 50},
        {"token_index": 0},
        {"token_index": 0, "volume": -1},
        {"token_index": 0, "volume": 201},
        {"token_index": 0, "volume": "50"},
        {"token_index": 0, "volume": True},
        [],
    ],
)
async def test_audio_volume_rejects_invalid_payloads(api, payload):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        VOLUME_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert queue.commands == []


@pytest.mark.parametrize("path", [FILTERS_PATH, VOLUME_PATH])
async def test_audio_effects_require_session(api, path):
    client, queue, _state_path = api

    response = await client.post(path, json={"token_index": 0})

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
    assert queue.commands == []


@pytest.mark.parametrize(
    "path",
    [FILTERS_PATH, VOLUME_PATH, FORCEFIX_PATH, LOOP_PATH, REPLAY_PATH],
)
async def test_audio_effects_require_csrf(api, path):
    client, queue, _state_path = api
    await pair(client)

    response = await client.post(path, json={"token_index": 0})

    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}
    assert queue.commands == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (FILTERS_PATH, {"token_index": 0, "filters": ["bass"]}),
        (VOLUME_PATH, {"token_index": 0, "volume": 50}),
    ],
)
async def test_audio_effects_return_503_without_command_queue(
    tmp_path, path, payload
):
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
        response = await client.post(
            path, json=payload, headers={"X-CSRF-Token": csrf}
        )
        body = await response.json()

    assert response.status == 503
    assert body == {"error": "voice_unavailable"}


async def test_queue_returns_audio_for_token(api):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.get(QUEUE_PATH, params={"token_index": "0"})

    assert response.status == 200
    assert await response.json() == {
        "audio": {"playing": True, "title": "x"}
    }


async def test_queue_returns_empty_object_for_unknown_token(api):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.get(QUEUE_PATH, params={"token_index": "9"})

    assert response.status == 200
    assert await response.json() == {"audio": {}}


async def test_queue_returns_all_audio_without_token_index(api):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.get(QUEUE_PATH)

    assert response.status == 200
    assert await response.json() == {"audio": STORED_AUDIO}


async def test_queue_returns_empty_audio_without_state_file(api):
    client, _queue, state_path = api
    await pair(client)
    state_path.unlink()

    response = await client.get(QUEUE_PATH)

    assert response.status == 200
    assert await response.json() == {"audio": {}}


@pytest.mark.parametrize(
    "params",
    [
        {"token_index": "-1"},
        {"token_index": "abc"},
        {"token_index": ""},
        {"token_index": "9" * 5000},
    ],
)
async def test_queue_rejects_invalid_token_index(api, params):
    client, _queue, _state_path = api
    await pair(client)

    response = await client.get(QUEUE_PATH, params=params)

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_play_returns_503_without_command_queue(tmp_path):
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
        response = await client.post(
            PLAY_PATH,
            json=_play_payload(),
            headers={"X-CSRF-Token": csrf},
        )
        body = await response.json()

    assert response.status == 503
    assert body == {"error": "voice_unavailable"}


async def test_play_returns_503_when_bot_is_offline(api):
    client, queue, _state_path = api
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH, json=_play_payload(), headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 503
    assert await response.json() == {"error": "bot_offline"}
    assert queue.commands == []


async def test_join_returns_503_when_bot_is_offline(api):
    client, queue, _state_path = api
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.post(
        JOIN_PATH,
        json={"token_index": 0, "channels": [CHANNEL]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 503
    assert await response.json() == {"error": "bot_offline"}
    assert queue.commands == []


@pytest.mark.parametrize(
    "path",
    [STOP_PATH, SKIP_PATH, FORCEFIX_PATH, LOOP_PATH, REPLAY_PATH],
)
async def test_audio_control_returns_503_without_command_queue(tmp_path, path):
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
        response = await client.post(
            path, json={"token_index": 0}, headers={"X-CSRF-Token": csrf}
        )
        body = await response.json()

    assert response.status == 503
    assert body == {"error": "voice_unavailable"}


async def test_play_rejects_unconfigured_token_index(api):
    client, queue, _state_path = api
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH,
        json=_play_payload(token_index=3),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "token_index is not configured" in body["details"]
    assert queue.commands == []


async def test_play_returns_503_when_liveness_check_raises(api):
    client, queue, _state_path = api
    client.app[ADAPTER_KEY] = RaisingAdapter()
    csrf = await pair(client)

    response = await client.post(
        PLAY_PATH, json=_play_payload(), headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 503
    assert await response.json() == {"error": "bot_offline"}
    assert queue.commands == []


@requires_search
async def test_search_returns_502_on_timeout(api, monkeypatch):
    client, _queue, _state_path = api
    csrf = await pair(client)

    def slow_search(_query):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(media, "_search_flat_entries", slow_search)
    monkeypatch.setattr(media, "SEARCH_TIMEOUT_SECONDS", 0.01)

    response = await client.post(
        SEARCH_PATH, json={"query": "lofi"}, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 502
    body = await response.json()
    assert body["error"] == "search_failed"
    assert body["message"]
