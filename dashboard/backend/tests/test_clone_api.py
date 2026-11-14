from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import ADAPTER_KEY, create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio


class FakeCloneQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


class FakeCloneResults:
    def read(self, request_id):
        if request_id == "known":
            return {"status": "success", "message": "done"}
        return None


class FakeOfflineAdapter:
    def can_queue(self):
        return False


class FakeOnlineAdapter:
    def can_queue(self):
        return True


async def pair(client) -> str:
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200
    return (await response.json())["csrf_token"]


@pytest_asyncio.fixture
async def clone_client(tmp_path):
    queue = FakeCloneQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        clone_queue=queue,
        clone_results=FakeCloneResults(),
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, queue


async def test_clone_queues_selected_options(clone_client):
    client, queue = clone_client
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/clone",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {
                "info": True,
                "structure": False,
                "emojis": True,
            },
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert body["request_id"]
    assert queue.commands == [
        {
            "request_id": body["request_id"],
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "options": {
                "info": True,
                "structure": False,
                "emojis": True,
            },
        }
    ]


async def test_clone_status_reads_result(clone_client):
    client, _queue = clone_client
    await pair(client)

    response = await client.get(
        "/api/v1/utility/clone/status?request_id=known"
    )
    body = await response.json()

    assert response.status == 200
    assert body == {"status": "success", "message": "done"}


async def test_clone_status_unknown_request(clone_client):
    client, _queue = clone_client
    await pair(client)

    response = await client.get(
        "/api/v1/utility/clone/status?request_id=missing"
    )
    body = await response.json()

    assert response.status == 404
    assert body["error"] == "not_found"


async def test_clone_returns_503_when_bot_offline(clone_client):
    client, queue = clone_client
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/clone",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {"info": True},
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 503
    assert await response.json() == {"error": "bot_offline"}
    assert queue.commands == []


async def test_clone_queues_when_bot_online(clone_client):
    client, queue = clone_client
    client.app[ADAPTER_KEY] = FakeOnlineAdapter()
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/clone",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {"info": True},
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert len(queue.commands) == 1
