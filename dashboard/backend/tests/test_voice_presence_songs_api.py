"""Tests for the dashboard Spotify songs API extension."""

from __future__ import annotations

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

SONGS_PATH = "/api/v1/presence/songs"
RESOLVE_PATH = "/api/v1/presence/songs/resolve"

TRACK_ID_ONE = "3IuxFX3kzxDRv4t9anPo43"
TRACK_ID_TWO = "3oIKYROTi2wREKdnqq3yAp"
IMAGE_HASH = "ab67616d00001e02ffbeabd7a6b240df9b086758"


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

    songs_path = (
        Path(config_path).resolve().parent / "data" / "songs.json"
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, queue, songs_path


def _song(
    name="Song",
    artist="Artist",
    track_id=TRACK_ID_ONE,
    duration_ms=147272,
    image=IMAGE_HASH,
    **extra,
):
    song = {
        "name": name,
        "artist": artist,
        "id": track_id,
        "duration_ms": duration_ms,
        "image": image,
    }
    song.update(extra)
    return song


def _compact_file(songs):
    if not songs:
        return "[]\n"
    return (
        "[\n"
        + ",\n".join(
            "  " + json.dumps(song, ensure_ascii=False) for song in songs
        )
        + "\n]\n"
    )


async def test_get_songs_returns_empty_when_missing(api):
    client, _queue, songs_path = api
    await pair(client)

    response = await client.get(SONGS_PATH)

    assert response.status == 200
    assert await response.json() == {"songs": []}
    assert not songs_path.exists()


async def test_get_songs_normalizes_existing_file(api):
    client, _queue, songs_path = api
    songs_path.parent.mkdir(parents=True)
    songs_path.write_text(
        json.dumps(
            [
                {
                    "name": "Song One",
                    "artist": "Artist One",
                    "id": (
                        f"https://open.spotify.com/track/{TRACK_ID_ONE}"
                        "?si=abc"
                    ),
                    "duration_ms": 147272,
                    "image": f"https://i.scdn.co/image/{IMAGE_HASH}",
                    "album": "Album One",
                },
                {
                    "name": "Song Two",
                    "id": f"spotify:track:{TRACK_ID_TWO}",
                    "duration_ms": "210000",
                },
                {"name": "Broken", "id": "short", "duration_ms": 147272},
            ]
        ),
        encoding="utf-8",
    )
    await pair(client)

    response = await client.get(SONGS_PATH)

    assert response.status == 200
    assert await response.json() == {
        "songs": [
            {
                "name": "Song One",
                "artist": "Artist One",
                "id": TRACK_ID_ONE,
                "duration_ms": 147272,
                "image": IMAGE_HASH,
                "album": "Album One",
            },
            {
                "name": "Song Two",
                "artist": "",
                "id": TRACK_ID_TWO,
                "duration_ms": 210000,
                "image": "",
            },
        ]
    }


async def test_put_songs_writes_compact_file(api):
    client, queue, songs_path = api
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH,
        json={
            "songs": [
                {
                    "name": "  Song One  ",
                    "artist": " Artist One ",
                    "id": (
                        f"https://open.spotify.com/track/{TRACK_ID_ONE}"
                        "?si=abc"
                    ),
                    "duration_ms": "147272",
                    "image": f"https://i.scdn.co/image/{IMAGE_HASH}",
                },
                {
                    "name": "Song Two",
                    "id": f"spotify:track:{TRACK_ID_TWO}",
                    "duration_ms": 210000,
                },
            ]
        },
        headers={"X-CSRF-Token": csrf},
    )

    expected_songs = [
        {
            "name": "Song One",
            "artist": "Artist One",
            "id": TRACK_ID_ONE,
            "duration_ms": 147272,
            "image": IMAGE_HASH,
        },
        {
            "name": "Song Two",
            "artist": "",
            "id": TRACK_ID_TWO,
            "duration_ms": 210000,
            "image": "",
        },
    ]
    assert response.status == 200
    assert await response.json() == {"ok": True}
    assert songs_path.read_text(encoding="utf-8") == _compact_file(
        expected_songs
    )
    assert (
        json.loads(songs_path.read_text(encoding="utf-8"))
        == expected_songs
    )
    assert queue.commands == []


INVALID_PAYLOADS = [
    {"songs": "not a list"},
    {"songs": [_song(name=f"Song {index}") for index in range(101)]},
    {"songs": [{"artist": "", "id": TRACK_ID_ONE, "duration_ms": 147272}]},
    {"songs": [_song(track_id="short")]},
    {"songs": [_song(duration_ms=0)]},
    {"songs": [_song(image="https://example.com/cover.jpg")]},
    {"songs": [_song(), "not an object"]},
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
async def test_put_songs_rejects_invalid_and_keeps_file(api, payload):
    client, queue, songs_path = api
    songs_path.parent.mkdir(parents=True)
    original = _compact_file([_song(name="Keep")])
    songs_path.write_text(original, encoding="utf-8")
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH, json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]
    assert songs_path.read_text(encoding="utf-8") == original
    assert queue.commands == []


async def test_put_songs_queues_nothing_when_bot_offline(api):
    client, queue, songs_path = api
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH,
        json={"songs": [_song()]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"ok": True}
    assert json.loads(songs_path.read_text(encoding="utf-8")) == [_song()]
    assert queue.commands == []


async def test_resolve_song_returns_metadata(api, monkeypatch):
    client, _queue, _songs_path = api
    csrf = await pair(client)
    calls = []

    def fake_fetch(track_id):
        calls.append(track_id)
        return {
            "name": "Song One",
            "artist": "Artist One",
            "id": track_id,
            "duration_ms": 147272,
            "image": f"https://i.scdn.co/image/{IMAGE_HASH}",
        }

    monkeypatch.setattr(presence_module, "_fetch_spotify_embed", fake_fetch)

    response = await client.post(
        RESOLVE_PATH,
        json={
            "url": f"https://open.spotify.com/track/{TRACK_ID_ONE}?si=abc"
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {
        "song": {
            "name": "Song One",
            "artist": "Artist One",
            "id": TRACK_ID_ONE,
            "duration_ms": 147272,
            "image": IMAGE_HASH,
        }
    }
    assert calls == [TRACK_ID_ONE]


async def test_resolve_song_rejects_invalid_url(api):
    client, _queue, _songs_path = api
    csrf = await pair(client)

    response = await client.post(
        RESOLVE_PATH,
        json={"url": "https://example.com/track/not-spotify"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert body["details"]


async def test_resolve_song_returns_502_when_fetch_fails(api, monkeypatch):
    client, _queue, _songs_path = api
    csrf = await pair(client)
    monkeypatch.setattr(
        presence_module, "_fetch_spotify_embed", lambda track_id: None
    )

    response = await client.post(
        RESOLVE_PATH,
        json={"url": f"spotify:track:{TRACK_ID_ONE}"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 502
    assert await response.json() == {"error": "resolve_failed"}


async def test_songs_endpoints_require_session_and_csrf(api):
    client, queue, songs_path = api

    response = await client.get(SONGS_PATH)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    response = await client.put(SONGS_PATH, json={"songs": []})
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    response = await client.post(
        RESOLVE_PATH, json={"url": f"spotify:track:{TRACK_ID_ONE}"}
    )
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    await pair(client)

    response = await client.put(SONGS_PATH, json={"songs": []})
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    response = await client.post(
        RESOLVE_PATH, json={"url": f"spotify:track:{TRACK_ID_ONE}"}
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    response = await client.get(SONGS_PATH)
    assert response.status == 200
    assert await response.json() == {"songs": []}

    assert queue.commands == []
    assert not songs_path.exists()


async def test_put_songs_rejects_lone_surrogate_name(api):
    client, queue, songs_path = api
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH,
        json={"songs": [_song(name="\ud800")]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "songs[0].name contains invalid characters" in body["details"]
    assert not songs_path.exists()
    assert not list(songs_path.parent.glob("*.tmp"))
    assert queue.commands == []


async def test_put_songs_rejects_lone_surrogate_album(api):
    client, queue, songs_path = api
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH,
        json={"songs": [_song(album="\ud800")]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "songs[0].album contains invalid characters" in body["details"]
    assert not songs_path.exists()
    assert not list(songs_path.parent.glob("*.tmp"))
    assert queue.commands == []


async def test_resolve_song_clamps_missing_duration(api, monkeypatch):
    client, _queue, _songs_path = api
    csrf = await pair(client)

    monkeypatch.setattr(
        presence_module,
        "_fetch_spotify_embed",
        lambda track_id: {
            "name": "Song One",
            "artist": "Artist One",
            "id": track_id,
            "image": "",
        },
    )

    response = await client.post(
        RESOLVE_PATH,
        json={"url": f"spotify:track:{TRACK_ID_ONE}"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    song = (await response.json())["song"]
    assert song["duration_ms"] == 1000

    put_response = await client.put(
        SONGS_PATH,
        json={"songs": [song]},
        headers={"X-CSRF-Token": csrf},
    )
    assert put_response.status == 200
    assert await put_response.json() == {"ok": True}


async def test_resolve_song_clamps_long_duration(api, monkeypatch):
    client, _queue, _songs_path = api
    csrf = await pair(client)

    monkeypatch.setattr(
        presence_module,
        "_fetch_spotify_embed",
        lambda track_id: {
            "name": "Long Song",
            "artist": "Artist One",
            "id": track_id,
            "duration_ms": 7_200_000,
            "image": "",
        },
    )

    response = await client.post(
        RESOLVE_PATH,
        json={"url": f"spotify:track:{TRACK_ID_ONE}"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    song = (await response.json())["song"]
    assert song["duration_ms"] == presence_module.SONG_DURATION_MAX_MS

    put_response = await client.put(
        SONGS_PATH,
        json={"songs": [song]},
        headers={"X-CSRF-Token": csrf},
    )
    assert put_response.status == 200
    assert await put_response.json() == {"ok": True}


async def test_spotify_embed_clamps_long_duration(monkeypatch):
    payload = {
        "props": {
            "pageProps": {
                "state": {
                    "data": {
                        "entity": {
                            "name": "Long Song",
                            "duration": 7_200_000,
                            "artists": [{"name": "Artist One"}],
                            "coverArt": {"sources": [{"url": "abc123"}]},
                        }
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script>"
    )
    monkeypatch.setattr(
        presence_module, "_http_get_text", lambda _url: html
    )

    song = presence_module._fetch_spotify_embed(TRACK_ID_ONE)

    assert song["duration_ms"] == presence_module.SONG_DURATION_MAX_MS


async def test_put_songs_rejects_duplicate_ids(api):
    client, queue, songs_path = api
    csrf = await pair(client)

    response = await client.put(
        SONGS_PATH,
        json={"songs": [_song(), _song(name="Other Song")]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert "songs[1].id is duplicated" in body["details"]
    assert not songs_path.exists()
    assert queue.commands == []
