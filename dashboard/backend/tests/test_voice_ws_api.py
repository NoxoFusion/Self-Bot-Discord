from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore
from dashboard.backend.voice_api import ws as ws_module

WS_PATH = "/api/v1/ws"


def _state(updated_at: int = 123) -> dict:
    return {
        "updated_at": updated_at,
        "guild_channels": {
            "111": [{"id": "222", "name": "General", "position": 0}]
        },
        "tokens": [
            {
                "index": 0,
                "username": "alice",
                "guild_channels": {
                    "111": [{"id": "222", "name": "General", "position": 0}]
                },
            }
        ],
    }


def test_slim_voice_strips_guild_channels_and_does_not_mutate():
    state = _state()
    state["tokens"].append({"index": 1, "username": "bob"})
    state["extra"] = "kept"

    slim = ws_module._slim_voice(state)

    assert slim is not state
    assert slim["tokens"] is not state["tokens"]
    assert "guild_channels" not in slim["tokens"][0]
    assert slim["tokens"][1] == {"index": 1, "username": "bob"}
    assert slim["updated_at"] == 123
    assert slim["extra"] == "kept"

    # The cached state object must be left untouched.
    assert state["tokens"][0]["guild_channels"] == {
        "111": [{"id": "222", "name": "General", "position": 0}]
    }
    assert state["tokens"][1] == {"index": 1, "username": "bob"}


def test_slim_voice_handles_non_dict_input():
    assert ws_module._slim_voice(None) == {}
    assert ws_module._slim_voice([]) == {}


def test_should_push_first_change_and_heartbeat():
    fingerprint = (1, "online", "alice", "111", 2, None)
    changed = (2, "online", "alice", "111", 2, None)

    assert ws_module._should_push(fingerprint, None, 0.0, 0.0) is True
    assert ws_module._should_push(changed, fingerprint, 100.0, 99.0) is True
    assert (
        ws_module._should_push(fingerprint, fingerprint, 109.9, 100.0) is False
    )
    assert ws_module._should_push(fingerprint, fingerprint, 110.0, 100.0) is True


@pytest_asyncio.fixture
async def ws_api(tmp_path, monkeypatch):
    state_path = tmp_path / "voice_state.json"
    state_path.write_text(json.dumps(_state()), encoding="utf-8")
    # Keep the token count independent from the repository's root config.
    monkeypatch.setattr(ws_module, "load_root_voice_tokens", lambda: [])
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        voice_state_path=state_path,
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, state_path


async def _pair_and_connect(client):
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return await client.ws_connect(WS_PATH)


@pytest.mark.asyncio
async def test_ws_sends_initial_frame_without_guild_channels(ws_api):
    client, _state_path = ws_api
    ws = await _pair_and_connect(client)
    try:
        frame = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
    finally:
        await ws.close()

    assert frame["type"] == "state"
    assert frame["tokens"] == 1
    assert frame["voice"]["updated_at"] == 123
    assert frame["voice"]["tokens"][0]["username"] == "alice"
    assert "guild_channels" not in frame["voice"]["tokens"][0]


@pytest.mark.asyncio
async def test_ws_stays_quiet_when_state_is_unchanged(ws_api):
    client, _state_path = ws_api
    ws = await _pair_and_connect(client)
    try:
        frame = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
        assert frame["type"] == "state"

        # The broadcaster interval is 2s, so half a tick with unchanged state
        # must not produce another frame.
        received = None
        with contextlib.suppress(asyncio.TimeoutError):
            received = await asyncio.wait_for(ws.receive(), timeout=0.5)
        assert received is None
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_ws_pushes_again_when_state_changes(ws_api):
    client, state_path = ws_api
    ws = await _pair_and_connect(client)
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
        assert first["voice"]["updated_at"] == 123

        new_updated_at = 456
        state_path.write_text(
            json.dumps(_state(new_updated_at)), encoding="utf-8"
        )

        frame = None
        deadline = asyncio.get_running_loop().time() + 4.0
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0
            frame = await asyncio.wait_for(
                ws.receive_json(), timeout=remaining
            )
            if frame.get("voice", {}).get("updated_at") == new_updated_at:
                break

        assert frame["voice"]["updated_at"] == new_updated_at
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_broadcast_loop_survives_a_failed_tick(monkeypatch):
    from dashboard.backend.app import ADAPTER_KEY, VOICE_STATE_PATH_KEY

    reads = {"count": 0}

    def flaky_read(_path):
        reads["count"] += 1
        if reads["count"] == 1:
            raise UnicodeDecodeError(
                "utf-8", b"\xff", 0, 1, "invalid start byte"
            )
        return {"updated_at": 1}

    class FakeAdapter:
        def get_status(self):
            return {"state": "online"}

    class FakeHub:
        def __init__(self):
            self.frames = []

        def __len__(self):
            return 1

        async def broadcast(self, payload):
            self.frames.append(payload)

    hub = FakeHub()
    app = {
        ws_module.WS_HUB_KEY: hub,
        ADAPTER_KEY: FakeAdapter(),
        VOICE_STATE_PATH_KEY: "unused",
    }
    monkeypatch.setattr(ws_module, "read_voice_state", flaky_read)
    monkeypatch.setattr(ws_module, "PUSH_INTERVAL_SECONDS", 0.01)

    task = asyncio.create_task(ws_module._broadcast_loop(app))
    try:
        deadline = asyncio.get_running_loop().time() + 2.0
        while not hub.frames and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert reads["count"] >= 2
    assert hub.frames
