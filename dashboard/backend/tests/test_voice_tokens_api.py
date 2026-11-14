from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import config as backend_config
from dashboard.backend.app import ADAPTER_KEY, create_app
from dashboard.backend.state_store import StateStore
from dashboard.backend.voice import TokenProfileStore, VoiceTokenService

pytestmark = pytest.mark.asyncio


class FakeVoiceService:
    def __init__(self):
        self.clear_calls = 0

    async def get_tokens(self):
        return {"tokens": [], "removed": 0}

    def clear_cache(self):
        self.clear_calls += 1


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
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=service,
        voice_state_path=tmp_path / "voice_state.json",
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, service, config_path


async def test_add_voice_token_validates_and_persists(api, monkeypatch):
    client, service, config_path = api
    csrf = await pair(client)
    calls = []

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        calls.append((token, method, path))
        if token == "root-bot-token":
            return 200, {"id": "1", "username": "main-account"}
        return 200, {
            "id": "42",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "abc",
        }

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "  new-token  "},
        headers={"X-CSRF-Token": csrf},
    )
    body = await response.json()

    assert response.status == 200
    assert body == {
        "ok": True,
        "token": {
            "username": "alice",
            "display_name": "Alice",
            "user_id": "42",
            "avatar_url": (
                "https://cdn.discordapp.com/avatars/42/abc.png?size=128"
            ),
        },
    }
    assert calls == [
        ("new-token", "GET", "/users/@me"),
        ("root-bot-token", "GET", "/users/@me"),
    ]
    assert "new-token" not in json.dumps(body)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["voice_token"] == ["existing-token", "new-token"]
    assert raw["token"] == "root-bot-token"
    assert raw["prefix"] == "!"
    assert raw["nested"] == {"keep": True}
    assert service.clear_calls == 1


async def test_add_voice_token_rejects_401(api, monkeypatch):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        return 401, {"message": "401: Unauthorized"}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "bad-token"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "invalid_token"}
    assert "bad-token" not in await response.text()
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_add_voice_token_reports_network_and_http_errors(
    api, monkeypatch
):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")

    async def network_error(token, method, path, json_body=None, timeout=8.0):
        return None, None

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", network_error
    )
    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "token-a"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 502
    assert await response.json() == {"error": "network_error"}

    async def http_error(token, method, path, json_body=None, timeout=8.0):
        return 500, {"message": "boom"}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", http_error
    )
    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "token-a"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 502
    assert await response.json() == {"error": "http_500"}

    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_delete_voice_token_removes_index_and_clears_cache(api):
    client, service, config_path = api
    csrf = await pair(client)
    write_config(config_path, voice_token=["token-a", "token-b", "token-c"])

    response = await client.delete(
        "/api/v1/voice/tokens",
        json={"token_index": 1},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"ok": True}

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["voice_token"] == ["token-a", "token-c"]
    assert raw["token"] == "root-bot-token"
    assert raw["prefix"] == "!"
    assert raw["nested"] == {"keep": True}
    assert service.clear_calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"token_index": 3},
        {"token_index": -1},
        {"token_index": "0"},
        {"token_index": True},
        {},
    ],
)
async def test_delete_voice_token_rejects_invalid_index(api, payload):
    client, service, config_path = api
    csrf = await pair(client)
    write_config(config_path, voice_token=["token-a", "token-b", "token-c"])
    before = config_path.read_text(encoding="utf-8")

    response = await client.delete(
        "/api/v1/voice/tokens",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["error"] == "validation_error"
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_voice_token_mutations_require_session_and_csrf(api, monkeypatch):
    client, service, config_path = api

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        return 200, {"id": "1", "username": "alice", "avatar": None}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )
    before = config_path.read_text(encoding="utf-8")

    response = await client.post(
        "/api/v1/voice/tokens", json={"token": "token-a"}
    )
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}

    await pair(client)
    response = await client.post(
        "/api/v1/voice/tokens", json={"token": "token-a"}
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    response = await client.delete(
        "/api/v1/voice/tokens", json={"token_index": 0}
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}

    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_get_voice_tokens_still_works(api):
    client, service, _config_path = api
    await pair(client)

    response = await client.get("/api/v1/voice/tokens")

    assert response.status == 200
    assert await response.json() == {
        "tokens": [],
        "removed": 0,
        "state_updated_at": None,
    }


async def test_get_voice_tokens_includes_audio_flags(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "index": 0,
                        "audio_active": True,
                        "audio_playing": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class AudioVoiceService(FakeVoiceService):
        async def get_tokens(self):
            return {
                "tokens": [{"index": 0, "username": "alice"}],
                "removed": 0,
            }

    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=AudioVoiceService(),
        voice_state_path=state_path,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        await pair(client)
        response = await client.get("/api/v1/voice/tokens")
        body = await response.json()

    assert response.status == 200
    token = body["tokens"][0]
    assert token["audio_active"] is True
    assert token["audio_playing"] is True


async def test_voice_tokens_delete_preflight_allows_delete(api):
    client, _service, _config_path = api

    response = await client.options(
        "/api/v1/voice/tokens",
        headers={
            "Origin": "http://127.0.0.1:4000",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status == 204
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]


async def test_voice_control_actions_require_auth(api):
    client, _service, _config_path = api

    requests = [
        (
            "/api/v1/voice/join",
            {"token_index": 0, "channels": ["123"]},
        ),
        (
            "/api/v1/voice/leave",
            {"token_index": 0, "channel_id": "123"},
        ),
        (
            "/api/v1/voice/soundboard/play",
            {"token_index": 0, "channel_id": "123", "sound_id": "456"},
        ),
    ]

    for path, body in requests:
        response = await client.post(path, json=body)
        assert response.status == 401, path
        assert await response.json() == {"error": "unauthorized"}


async def test_voice_control_actions_require_csrf(api):
    client, _service, _config_path = api
    await pair(client)

    requests = [
        (
            "/api/v1/voice/join",
            {"token_index": 0, "channels": ["123"]},
        ),
        (
            "/api/v1/voice/leave",
            {"token_index": 0, "channel_id": "123"},
        ),
        (
            "/api/v1/voice/soundboard/play",
            {"token_index": 0, "channel_id": "123", "sound_id": "456"},
        ),
    ]

    for path, body in requests:
        response = await client.post(path, json=body)
        assert response.status == 403, path
        assert await response.json() == {"error": "csrf_failed"}


async def test_add_root_voice_token_rejects_empty_and_creates_list(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "config.json"
    write_config(config_path, voice_token="legacy-value")
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    assert backend_config.add_root_voice_token("   ") is False
    assert backend_config.add_root_voice_token("token-a") is True

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["voice_token"] == ["token-a"]
    assert raw["token"] == "root-bot-token"


async def test_voice_token_service_clear_cache_refreshes_pool():
    calls = 0

    async def fetcher(token, method, path, json_body=None):
        nonlocal calls
        calls += 1
        return 200, {"id": "1", "username": "alice", "avatar": None}

    service = VoiceTokenService(
        token_loader=lambda: ["token-a"],
        fetcher=fetcher,
        ttl=60,
    )

    await service.get_tokens()
    await service.get_tokens()
    assert calls == 1

    service.clear_cache()
    await service.get_tokens()
    assert calls == 2


async def test_add_voice_token_rejects_duplicate(api, monkeypatch):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        if token == "root-bot-token":
            return 200, {"id": "1", "username": "main-account"}
        return 200, {"id": "42", "username": "alice", "avatar": None}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "existing-token"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 409
    assert await response.json() == {"error": "token_already_exists"}
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_add_voice_token_rejects_bot_token(api, monkeypatch):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        return 200, {
            "id": "42",
            "username": "bot-user",
            "avatar": None,
            "bot": True,
        }

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "bot-token"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "bot_token_not_supported"}
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


class FakeVoiceQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


async def test_add_and_delete_enqueue_voice_reload(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    queue = FakeVoiceQueue()
    service = FakeVoiceService()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=service,
        voice_command_queue=queue,
    )

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        if token == "root-bot-token":
            return 200, {"id": "1", "username": "main-account"}
        return 200, {"id": "42", "username": "alice", "avatar": None}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        csrf = await pair(client)

        response = await client.post(
            "/api/v1/voice/tokens",
            json={"token": "new-token"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200
        assert queue.commands == [{"action": "reload"}]

        response = await client.delete(
            "/api/v1/voice/tokens",
            json={"token_index": 1},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200
        assert queue.commands == [
            {"action": "reload"},
            {"action": "reload"},
        ]
        assert service.clear_calls == 2


class FakeStatusAdapter:
    def __init__(self, user_id):
        self._user_id = user_id

    def get_status(self):
        return {"user_id": self._user_id}


async def test_add_voice_token_rejects_main_account_session_token(
    api, monkeypatch
):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")
    client.app[ADAPTER_KEY] = FakeStatusAdapter("42")

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        return 200, {"id": "42", "username": "main-account"}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "another-session-of-main"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "main_account_session_token"}
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0


async def test_add_voice_token_rejects_main_session_when_bot_offline(
    api, monkeypatch
):
    client, service, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")
    client.app[ADAPTER_KEY] = FakeStatusAdapter(None)
    calls = []

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        calls.append((token, method, path))
        return 200, {"id": "42", "username": "main-account"}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "another-session-of-main"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "main_account_session_token"}
    assert config_path.read_text(encoding="utf-8") == before
    assert service.clear_calls == 0
    assert calls == [
        ("another-session-of-main", "GET", "/users/@me"),
        ("root-bot-token", "GET", "/users/@me"),
    ]

    # The resolved main account id is cached on the app, so a second session
    # token is rejected without another /users/@me call for the main token.
    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "second-session-of-main"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    assert await response.json() == {"error": "main_account_session_token"}
    assert calls == [
        ("another-session-of-main", "GET", "/users/@me"),
        ("root-bot-token", "GET", "/users/@me"),
        ("second-session-of-main", "GET", "/users/@me"),
    ]


async def test_add_voice_token_allows_exact_main_token(api, monkeypatch):
    client, service, config_path = api
    csrf = await pair(client)
    client.app[ADAPTER_KEY] = FakeStatusAdapter("42")

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        return 200, {"id": "42", "username": "main-account"}

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    response = await client.post(
        "/api/v1/voice/tokens",
        json={"token": "root-bot-token"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert "root-bot-token" in raw["voice_token"]
    assert service.clear_calls == 1


async def test_get_voice_tokens_uses_cached_profile_when_state_has_no_username(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.json"
    write_config(config_path, voice_token=["token-a"])
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    state_path = tmp_path / "voice_state.json"
    state_path.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "index": 0,
                        "username": None,
                        "user_id": None,
                        "channels": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class StateVoiceService(FakeVoiceService):
        async def get_tokens(self):
            return {
                "tokens": [
                    {
                        "index": 0,
                        "username": None,
                        "display_name": None,
                        "user_id": None,
                        "avatar_url": None,
                    }
                ],
                "removed": 0,
            }

    async def fetcher(token, method, path, json_body=None):
        return None, None

    store = TokenProfileStore(lambda: ["token-a"], fetcher=fetcher)
    store.remember(
        0,
        {
            "id": "42",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "abc",
        },
    )

    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=StateVoiceService(),
        token_profile_store=store,
        voice_state_path=state_path,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        await pair(client)
        response = await client.get("/api/v1/voice/tokens")
        body = await response.json()

    assert response.status == 200
    token = body["tokens"][0]
    assert token["username"] == "alice"
    assert token["display_name"] == "Alice"
    assert token["user_id"] == "42"
    assert "/avatars/42/abc.png" in token["avatar_url"]


async def test_add_voice_token_remembers_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path, voice_token=[])
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    async def fetcher(token, method, path, json_body=None):
        return None, None

    store = TokenProfileStore(lambda: [], fetcher=fetcher)
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=FakeVoiceService(),
        token_profile_store=store,
    )

    async def fake_fetch(token, method, path, json_body=None, timeout=8.0):
        if token == "root-bot-token":
            return 200, {"id": "1", "username": "main-account"}
        return 200, {
            "id": "42",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "abc",
        }

    monkeypatch.setattr(
        "dashboard.backend.app.fetch_discord_json", fake_fetch
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        csrf = await pair(client)
        response = await client.post(
            "/api/v1/voice/tokens",
            json={"token": "new-token"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200

    profile = store.profile_for(0)
    assert profile is not None
    assert profile["username"] == "alice"


async def test_delete_voice_token_forgets_and_shifts(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path, voice_token=["token-a", "token-b"])
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    async def fetcher(token, method, path, json_body=None):
        return None, None

    store = TokenProfileStore(lambda: [], fetcher=fetcher)
    store.remember(0, {"id": "1", "username": "alice"})
    store.remember(1, {"id": "2", "username": "bob"})

    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_service=FakeVoiceService(),
        token_profile_store=store,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        csrf = await pair(client)
        response = await client.delete(
            "/api/v1/voice/tokens",
            json={"token_index": 0},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status == 200

    assert store.profile_for(0)["username"] == "bob"
    assert store.profile_for(1) is None
