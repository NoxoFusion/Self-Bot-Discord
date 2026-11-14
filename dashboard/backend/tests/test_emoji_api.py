from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from dashboard.backend.app import ADAPTER_KEY, create_app
from dashboard.backend.state_store import StateStore

pytestmark = pytest.mark.asyncio


class FakeEmojiQueue:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)


class FakeEmojiResults:
    def read(self, request_id):
        if request_id == "known":
            return {"status": "success", "message": "copied 2/2"}
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
async def emoji_client(tmp_path):
    queue = FakeEmojiQueue()
    app = create_app(
        config={},
        state_store=StateStore(tmp_path / "runtime_state.json"),
        pairing_code="123456",
        emoji_queue=queue,
        emoji_results=FakeEmojiResults(),
    )

    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as client:
        yield client, queue


async def test_emoji_copy_queues_request(emoji_client):
    client, queue = emoji_client
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/emoji-copy",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "emoji_ids": ["333", "444"],
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
            "emoji_ids": ["333", "444"],
        }
    ]


async def test_emoji_copy_status_reads_result(emoji_client):
    client, _queue = emoji_client
    await pair(client)

    response = await client.get(
        "/api/v1/utility/emoji-copy/status?request_id=known"
    )
    body = await response.json()

    assert response.status == 200
    assert body == {"status": "success", "message": "copied 2/2"}


async def test_emoji_copy_status_unknown_request(emoji_client):
    client, _queue = emoji_client
    await pair(client)

    response = await client.get(
        "/api/v1/utility/emoji-copy/status?request_id=missing"
    )
    body = await response.json()

    assert response.status == 404
    assert body["error"] == "not_found"


async def test_emoji_copy_returns_503_when_bot_offline(emoji_client):
    client, queue = emoji_client
    client.app[ADAPTER_KEY] = FakeOfflineAdapter()
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/emoji-copy",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "emoji_ids": ["333"],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 503
    assert await response.json() == {"error": "bot_offline"}
    assert queue.commands == []


async def test_emoji_copy_queues_when_bot_online(emoji_client):
    client, queue = emoji_client
    client.app[ADAPTER_KEY] = FakeOnlineAdapter()
    csrf = await pair(client)

    response = await client.post(
        "/api/v1/utility/emoji-copy",
        json={
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "emoji_ids": ["333"],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status == 200
    body = await response.json()
    assert body["queued"] is True
    assert len(queue.commands) == 1
