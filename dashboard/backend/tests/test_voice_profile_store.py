from __future__ import annotations

import pytest

from dashboard.backend.voice import TokenProfileStore

pytestmark = pytest.mark.asyncio


async def test_warm_up_fetches_each_token_once():
    calls = []

    async def fetcher(token, method, path, json_body=None):
        calls.append((token, method, path))
        return 200, {
            "id": "42",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "abc",
        }

    store = TokenProfileStore(
        lambda: ["token-a", "token-b"], fetcher=fetcher
    )

    await store.warm_up()
    await store.warm_up()

    assert calls == [
        ("token-a", "GET", "/users/@me"),
        ("token-b", "GET", "/users/@me"),
    ]
    profile = store.profile_for(0)
    assert profile is not None
    assert profile["username"] == "alice"
    assert profile["display_name"] == "Alice"
    assert profile["user_id"] == "42"
    assert profile["avatar_url"] == (
        "https://cdn.discordapp.com/avatars/42/abc.png?size=128"
    )


async def test_warm_up_marks_failures_attempted():
    calls = []

    async def fetcher(token, method, path, json_body=None):
        calls.append(token)
        return None, None

    store = TokenProfileStore(lambda: ["token-a"], fetcher=fetcher)

    await store.warm_up()
    await store.warm_up()

    assert calls == ["token-a"]
    assert store.profile_for(0) is None


async def test_warm_up_skips_empty_tokens():
    calls = []

    async def fetcher(token, method, path, json_body=None):
        calls.append(token)
        return 200, {"id": "7", "username": "bob"}

    store = TokenProfileStore(lambda: ["", "tok"], fetcher=fetcher)

    await store.warm_up()

    assert calls == ["tok"]
    assert store.profile_for(0) is None
    assert store.profile_for(1)["username"] == "bob"


async def test_warm_up_skips_profile_when_token_index_shifted():
    tokens = ["token-a", "token-b"]

    async def fetcher(token, method, path, json_body=None):
        if token == "token-b":
            # Simulate a concurrent delete of index 0 while this fetch is
            # in flight: token-b shifts down to index 0.
            tokens.pop(0)
            return 200, {"id": "2", "username": "bob"}
        return 200, {"id": "1", "username": "alice"}

    store = TokenProfileStore(lambda: tokens, fetcher=fetcher)

    await store.warm_up()

    # token-b now lives at index 0; the stale index must not get a profile.
    assert store.profile_for(1) is None
    assert store.profile_for(0)["username"] == "alice"


async def test_warm_up_remembers_when_index_stable():
    async def fetcher(token, method, path, json_body=None):
        return 200, {"id": token, "username": token}

    store = TokenProfileStore(
        lambda: ["token-a", "token-b"], fetcher=fetcher
    )

    await store.warm_up()

    assert store.profile_for(0)["username"] == "token-a"
    assert store.profile_for(1)["username"] == "token-b"


async def test_remember_overrides_state_fields():
    store = TokenProfileStore(lambda: [])
    store.remember(
        0,
        {
            "id": "42",
            "username": "alice",
            "global_name": "Alice",
            "avatar": "a_xyz",
        },
    )
    token = {
        "index": 0,
        "username": None,
        "display_name": None,
        "user_id": None,
        "avatar_url": None,
    }

    store.apply(0, token)

    assert token == {
        "index": 0,
        "username": "alice",
        "display_name": "Alice",
        "user_id": "42",
        "avatar_url": (
            "https://cdn.discordapp.com/avatars/42/a_xyz.gif?size=128"
        ),
    }


async def test_forget_shifts_later_indices():
    store = TokenProfileStore(lambda: [])
    store.remember(0, {"id": "1", "username": "one"})
    store.remember(1, {"id": "2", "username": "two"})
    store.remember(2, {"id": "3", "username": "three"})

    store.forget(1)

    assert store.profile_for(0)["username"] == "one"
    assert store.profile_for(1)["username"] == "three"
    assert store.profile_for(2) is None


async def test_profile_from_user_rejects_invalid():
    assert TokenProfileStore.profile_from_user({}) is None
    assert TokenProfileStore.profile_from_user({"id": "42"}) is None
    assert (
        TokenProfileStore.profile_from_user(
            {"id": "42", "username": ""}
        )
        is None
    )
