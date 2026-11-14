from __future__ import annotations

import json
import logging

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend import config as backend_config
from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio

PROFILE = {
    "username": "alice",
    "display_name": "Alice",
    "user_id": "123456789012345678",
    "avatar_url": "https://cdn.example/avatar.png",
    "banner_url": None,
    "accent_color": None,
    "created_at": "2015-12-07T16:13:12.216000+00:00",
    "premium_type": 0,
    "badges": [],
}


class FakeProfileService:
    async def get(self):
        return dict(PROFILE)


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
        yield client, config_path


async def test_get_settings_requires_a_session(api):
    client, _ = api

    response = await client.get("/api/v1/settings")

    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}


async def test_get_settings_returns_prefix_and_profile(api):
    client, _ = api
    await pair(client)

    response = await client.get("/api/v1/settings")

    assert response.status == 200
    assert await response.json() == {"prefix": "!", "profile": PROFILE}


async def test_get_settings_returns_null_profile_without_service(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", config_path)

    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        await pair(client)
        response = await client.get("/api/v1/settings")
        assert response.status == 200
        assert await response.json() == {"prefix": "!", "profile": None}


@pytest.mark.parametrize(
    "prefix",
    ["", "   ", "abcdef", "a b", "two words", 123, None],
)
async def test_put_settings_prefix_rejects_invalid_values(api, prefix):
    client, config_path = api
    csrf = await pair(client)
    before = config_path.read_text(encoding="utf-8")

    response = await client.put(
        "/api/v1/settings/prefix",
        json={"prefix": prefix},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 400
    body = await response.json()
    assert body["saved"] is False
    assert body["error"]
    assert config_path.read_text(encoding="utf-8") == before
    assert not (config_path.parent / "data" / "reload.flag").exists()


async def test_put_settings_prefix_saves_and_requests_reload(api):
    client, config_path = api
    csrf = await pair(client)

    response = await client.put(
        "/api/v1/settings/prefix",
        json={"prefix": " ? "},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {
        "saved": True,
        "prefix": "?",
        "reload_requested": True,
    }

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["prefix"] == "?"
    assert raw["token"] == "root-bot-token"
    assert raw["voice_token"] == ["existing-token"]
    assert raw["nested"] == {"keep": True}

    flag_path = config_path.parent / "data" / "reload.flag"
    assert flag_path.exists()
    assert flag_path.read_text(encoding="utf-8").strip()


async def test_put_settings_prefix_requires_csrf(api):
    client, config_path = api
    await pair(client)
    before = config_path.read_text(encoding="utf-8")

    response = await client.put(
        "/api/v1/settings/prefix",
        json={"prefix": "?"},
    )

    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}
    assert config_path.read_text(encoding="utf-8") == before


async def test_post_settings_reload_creates_flag(api):
    client, config_path = api
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/settings/reload",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    assert await response.json() == {"requested": True}

    flag_path = config_path.parent / "data" / "reload.flag"
    assert flag_path.exists()
    assert flag_path.read_text(encoding="utf-8").strip()


async def test_put_settings_prefix_reports_reload_failure(api, monkeypatch):
    client, config_path = api
    csrf = await pair(client)
    monkeypatch.setattr(
        "dashboard.backend.app.request_bot_reload", lambda: False
    )

    response = await client.put(
        "/api/v1/settings/prefix",
        json={"prefix": "?"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 500
    assert await response.json() == {"error": "reload_request_failed"}
    assert json.loads(config_path.read_text(encoding="utf-8"))["prefix"] == "?"


class _FakeConfigPath:
    """Minimal path stand-in that returns scripted read results."""

    def __init__(self, reads):
        self._reads = list(reads)
        self.read_count = 0
        self.written = None
        self.name = "config.json"

    def read_text(self, encoding="utf-8"):
        index = min(self.read_count, len(self._reads) - 1)
        self.read_count += 1
        return self._reads[index]

    def with_name(self, name):
        return _FakeTempPath(self)


class _FakeTempPath:
    def __init__(self, owner):
        self._owner = owner

    def write_text(self, text, encoding="utf-8"):
        self._owner.written = text


async def test_set_root_prefix_retries_when_another_process_writes(
    monkeypatch,
):
    stale = json.dumps({"prefix": "!", "voice_token": ["a"]})
    concurrent = json.dumps({"prefix": "!", "voice_token": ["a", "b"]})
    fake_path = _FakeConfigPath(
        [stale, concurrent, concurrent, concurrent]
    )
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", fake_path)
    monkeypatch.setattr(backend_config.os, "replace", lambda *args: None)

    assert backend_config.set_root_prefix("?") is True

    assert fake_path.read_count == 4
    written = json.loads(fake_path.written)
    assert written["prefix"] == "?"
    assert written["voice_token"] == ["a", "b"]


async def test_load_config_warns_when_api_host_is_not_loopback(
    tmp_path, caplog
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"api_host": "0.0.0.0"}), encoding="utf-8"
    )

    with caplog.at_level(
        logging.WARNING, logger="dashboard.backend.config"
    ):
        config = backend_config.load_config(config_path)

    assert config["api_host"] == "0.0.0.0"
    assert any(
        "exposed beyond this machine" in record.getMessage()
        for record in caplog.records
    )
