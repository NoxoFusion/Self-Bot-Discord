from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.backend.app import create_app
from dashboard.backend.state_store import StateStore

TEST_CONFIG = {
    "api_host": "127.0.0.1",
    "api_port": 8765,
    "allowed_origins": [
        "http://127.0.0.1:4000",
        "http://localhost:4000",
    ],
    "bot_token": "",
    "application_id": "",
    "guild_id": "",
}


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "runtime_state.json"


@pytest.fixture
def app(state_path: Path):
    return create_app(
        config=TEST_CONFIG,
        state_store=StateStore(state_path),
        pairing_code="123456",
    )


@pytest_asyncio.fixture
async def client(app):
    # TestServer binds to a random port.  Override Host so requests pass the
    # same allowlist used by the real 127.0.0.1:8765 server.
    async with TestClient(
        TestServer(app),
        headers={"Host": "127.0.0.1:8765"},
    ) as test_client:
        yield test_client
