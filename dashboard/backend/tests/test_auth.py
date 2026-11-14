from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_wrong_pairing_code_is_rejected(client):
    response = await client.post("/api/v1/pair", json={"code": "000000"})
    assert response.status == 401
    assert await response.json() == {"error": "invalid_code"}


async def test_pairing_sets_cookie_and_returns_csrf(client):
    response = await client.post("/api/v1/pair", json={"code": "123456"})
    assert response.status == 200

    payload = await response.json()
    assert payload["authenticated"] is True
    assert isinstance(payload["csrf_token"], str)
    assert payload["csrf_token"]

    cookie = response.cookies["sb_dashboard_session"]
    assert cookie.value
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/"
    assert cookie["max-age"] == "28800"

    session_response = await client.get("/api/v1/session")
    assert session_response.status == 200
    assert await session_response.json() == {
        "authenticated": True,
        "csrf_token": payload["csrf_token"],
    }


async def test_session_without_cookie_is_unauthenticated(client):
    response = await client.get("/api/v1/session")
    assert response.status == 401
    assert await response.json() == {"authenticated": False}


async def test_logout_requires_csrf_and_clears_session(client):
    pair_response = await client.post("/api/v1/pair", json={"code": "123456"})
    csrf = (await pair_response.json())["csrf_token"]

    missing = await client.post("/api/v1/logout")
    assert missing.status == 403
    assert await missing.json() == {"error": "csrf_failed"}

    wrong = await client.post(
        "/api/v1/logout",
        headers={"X-CSRF-Token": "not-the-token"},
    )
    assert wrong.status == 403
    assert await wrong.json() == {"error": "csrf_failed"}

    ok = await client.post(
        "/api/v1/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status == 204
    assert await ok.text() == ""

    after = await client.get("/api/v1/session")
    assert after.status == 401
    assert await after.json() == {"authenticated": False}


async def test_mutation_without_csrf_is_forbidden(client):
    await client.post("/api/v1/pair", json={"code": "123456"})

    response = await client.put(
        "/api/v1/afk",
        json={"enabled": False, "reason": ""},
    )
    assert response.status == 403
    assert await response.json() == {"error": "csrf_failed"}


async def test_sixth_wrong_pairing_attempt_is_rate_limited(client):
    for _ in range(5):
        response = await client.post("/api/v1/pair", json={"code": "000000"})
        assert response.status == 401

    response = await client.post("/api/v1/pair", json={"code": "000000"})
    assert response.status == 429
    assert await response.json() == {"error": "rate_limited"}


async def test_pairing_code_rotates_after_successful_pair(client):
    first = await client.post("/api/v1/pair", json={"code": "123456"})
    assert first.status == 200

    reused = await client.post("/api/v1/pair", json={"code": "123456"})
    assert reused.status == 401
    assert await reused.json() == {"error": "invalid_code"}


async def test_invalid_host_is_rejected(client):
    response = await client.get(
        "/api/v1/session",
        headers={"Host": "evil.example:8765"},
    )
    assert response.status == 403
    assert await response.json() == {"error": "forbidden_host"}


async def test_invalid_origin_is_rejected(client):
    response = await client.get(
        "/api/v1/session",
        headers={"Origin": "http://evil.example"},
    )
    assert response.status == 403
    assert await response.json() == {"error": "forbidden_origin"}


async def test_allowed_origin_is_accepted(client):
    response = await client.get(
        "/api/v1/session",
        headers={"Origin": "http://localhost:4000"},
    )
    assert response.status == 401
    assert await response.json() == {"authenticated": False}
