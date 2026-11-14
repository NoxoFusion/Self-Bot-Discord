from __future__ import annotations

import json

import pytest
from aiohttp import WSServerHandshakeError

from dashboard.backend.ws_hub import WsHub

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []
        self.closed = False
        self.close_calls = 0

    async def send_str(self, message: str) -> None:
        if self.fail:
            raise ConnectionResetError("socket is dead")
        self.sent.append(message)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


async def test_broadcast_sends_the_same_json_to_every_socket():
    hub = WsHub()
    first = FakeWebSocket()
    second = FakeWebSocket()
    hub.add(first)
    hub.add(second)

    await hub.broadcast({"type": "state", "tokens": 2})

    assert first.sent == second.sent
    assert json.loads(first.sent[0]) == {"type": "state", "tokens": 2}


async def test_broadcast_discards_a_dead_socket():
    hub = WsHub()
    alive = FakeWebSocket()
    dead = FakeWebSocket(fail=True)
    hub.add(alive)
    hub.add(dead)

    await hub.broadcast({"type": "state"})

    assert len(hub) == 1
    assert hub.sockets == (alive,)
    assert len(alive.sent) == 1


async def test_broadcast_skips_already_closed_sockets():
    hub = WsHub()
    closed = FakeWebSocket()
    closed.closed = True
    hub.add(closed)

    await hub.broadcast({"type": "state"})

    assert len(hub) == 0
    assert closed.sent == []


async def test_close_all_closes_every_socket_and_clears_the_hub():
    hub = WsHub()
    first = FakeWebSocket()
    second = FakeWebSocket()
    hub.add(first)
    hub.add(second)

    await hub.close_all()

    assert first.close_calls == 1
    assert second.close_calls == 1
    assert len(hub) == 0


async def test_ws_endpoint_requires_a_session(client):
    with pytest.raises(WSServerHandshakeError) as excinfo:
        await client.ws_connect("/api/v1/ws")

    assert excinfo.value.status == 401


async def test_ws_endpoint_pushes_state_after_pairing(client):
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200

    ws = await client.ws_connect("/api/v1/ws")
    try:
        message = await ws.receive_json(timeout=2)
    finally:
        await ws.close()

    assert message["type"] == "state"
    assert message["bot"]["state"] == "offline"
    assert isinstance(message["voice"], dict)
    assert isinstance(message["tokens"], int)


async def test_ws_endpoint_accepts_an_allowed_origin(client):
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200

    ws = await client.ws_connect(
        "/api/v1/ws", headers={"Origin": "http://127.0.0.1:4000"}
    )
    try:
        message = await ws.receive_json(timeout=2)
    finally:
        await ws.close()

    assert message["type"] == "state"
