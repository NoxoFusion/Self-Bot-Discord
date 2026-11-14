from __future__ import annotations

import json

import pytest

from dashboard.backend.voice import (
    SoundboardService,
    VoiceCommandQueue,
    VoiceError,
    VoiceTokenService,
    read_voice_state,
)
from dashboard.backend import config as backend_config


def test_voice_command_queue_writes_one_spool_file_per_command(tmp_path):
    path = tmp_path / "voice_commands.json"
    queue = VoiceCommandQueue(path)

    first = {"action": "join", "token_index": 0, "channels": ["123"]}
    second = {"action": "leave", "token_index": 0, "channel_id": "123"}
    queue.enqueue(first)
    queue.enqueue(second)

    files = sorted((tmp_path / "voice_commands.spool").glob("*.json"))
    assert len(files) == 2
    commands = [json.loads(item.read_text(encoding="utf-8")) for item in files]
    assert sorted(commands, key=lambda command: command["action"]) == [
        first,
        second,
    ]
    assert not path.exists()


def test_voice_command_queue_two_enqueues_create_distinct_files(tmp_path):
    path = tmp_path / "voice_commands.json"
    queue = VoiceCommandQueue(path)
    spool = tmp_path / "voice_commands.spool"

    queue.enqueue({"action": "join", "token_index": 0, "channels": ["123"]})
    first_files = {item.name for item in spool.glob("*.json")}

    queue.enqueue({"action": "leave", "token_index": 0, "channel_id": "123"})
    second_files = {item.name for item in spool.glob("*.json")}

    assert len(first_files) == 1
    assert len(second_files) == 2
    assert first_files < second_files
    assert not path.exists()


def test_read_voice_state_returns_empty_for_missing_or_invalid_file(tmp_path):
    assert read_voice_state(tmp_path / "missing.json") == {}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    assert read_voice_state(invalid) == {}

    undecodable = tmp_path / "undecodable.json"
    undecodable.write_bytes(b"\xff\xfe\x00\x00")
    assert read_voice_state(undecodable) == {}


def test_read_voice_state_returns_dict(tmp_path):
    path = tmp_path / "voice_state.json"
    path.write_text(json.dumps({"tokens": [{"index": 0}]}), encoding="utf-8")

    assert read_voice_state(path) == {"tokens": [{"index": 0}]}


def test_read_voice_state_caches_by_mtime(tmp_path):
    path = tmp_path / "voice_state.json"
    path.write_text(
        json.dumps({"updated_at": 1, "tokens": [{"index": 0}]}),
        encoding="utf-8",
    )

    first = read_voice_state(path)
    second = read_voice_state(path)

    assert first is second

    path.write_text(
        json.dumps({"updated_at": 2, "tokens": []}),
        encoding="utf-8",
    )
    third = read_voice_state(path)

    assert third is not first
    assert third == {"updated_at": 2, "tokens": []}


def test_load_root_voice_tokens_preserves_indices(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"voice_token": ["token-a", " ", "token-b"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(backend_config, "ROOT_CONFIG_PATH", path)

    assert backend_config.load_root_voice_tokens() == [
        "token-a",
        "",
        "token-b",
    ]


@pytest.mark.asyncio
async def test_voice_token_service_reports_live_tokens_and_removes_401():
    calls = []

    async def fetcher(token, method, path, json_body=None):
        calls.append((token, method, path))
        if token == "token-a":
            return 200, {
                "id": "1",
                "username": "alice",
                "global_name": "Alice",
                "avatar": "abc",
            }
        if token == "token-b":
            return 401, {"message": "401: Unauthorized"}
        return None, None

    service = VoiceTokenService(
        token_loader=lambda: ["token-a", "token-b", "token-c"],
        fetcher=fetcher,
        ttl=60,
    )

    result = await service.get_tokens()

    assert result["removed"] == 1
    assert [token["index"] for token in result["tokens"]] == [0, 2]
    assert result["tokens"][0]["username"] == "alice"
    assert result["tokens"][0]["display_name"] == "Alice"
    assert result["tokens"][0]["avatar_url"].endswith("/avatars/1/abc.png?size=128")
    assert result["tokens"][1]["error"] == "network_error"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_voice_token_service_preserves_config_indices():
    async def fetcher(token, method, path, json_body=None):
        return 200, {"id": token, "username": token, "avatar": None}

    service = VoiceTokenService(
        token_loader=lambda: ["token-a", "", "token-b"],
        fetcher=fetcher,
        ttl=60,
    )

    result = await service.get_tokens()

    assert [token["index"] for token in result["tokens"]] == [0, 2]


@pytest.mark.asyncio
async def test_voice_token_service_calls_on_unauthorized():
    async def fetcher(token, method, path, json_body=None):
        if token == "bad":
            return 401, {"message": "401: Unauthorized"}
        return 200, {"id": "1", "username": "alice", "avatar": None}

    removed_indices: list[int] = []
    service = VoiceTokenService(
        token_loader=lambda: ["good", "bad"],
        fetcher=fetcher,
        ttl=60,
        on_unauthorized=removed_indices.extend,
    )

    result = await service.get_tokens()

    assert result["removed"] == 1
    assert removed_indices == [1]


@pytest.mark.asyncio
async def test_voice_token_service_caches_results():
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


@pytest.mark.asyncio
async def test_soundboard_service_lists_and_plays_sounds():
    calls = []

    async def fetcher(token, method, path, json_body=None):
        calls.append((token, method, path, json_body))
        if path.endswith("/soundboard-sounds"):
            return 200, {
                "items": [
                    {"sound_id": "1", "name": "Quack", "emoji_name": "🦆"}
                ]
            }
        if path.endswith("/soundboard-default-sounds"):
            return 200, [{"sound_id": "2", "name": "Airhorn"}]
        if path.endswith("/send-soundboard-sound"):
            return 204, None
        return 404, None

    service = SoundboardService(
        token_loader=lambda: ["token-a"],
        fetcher=fetcher,
    )

    server_sounds = await service.list_server_sounds(0, "123")
    default_sounds = await service.list_default_sounds(0)
    played = await service.play(0, "456", "1", source_guild_id="123")

    assert server_sounds[0]["name"] == "Quack"
    assert default_sounds[0]["name"] == "Airhorn"
    assert played == {"ok": True}
    assert calls[-1] == (
        "token-a",
        "POST",
        "/channels/456/send-soundboard-sound",
        {"sound_id": "1", "source_guild_id": "123"},
    )


@pytest.mark.asyncio
async def test_soundboard_service_rejects_missing_token():
    service = SoundboardService(
        token_loader=lambda: [],
        fetcher=lambda *args, **kwargs: None,
    )

    with pytest.raises(VoiceError) as exc:
        await service.list_default_sounds(0)

    assert exc.value.status == 400
    assert exc.value.message == "token_not_configured"


@pytest.mark.asyncio
async def test_get_tokens_uses_bot_state_without_rest_calls():
    calls = []

    async def fetcher(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, {}

    service = VoiceTokenService(
        lambda: ["token-a", "token-b"],
        fetcher=fetcher,
        state_reader=lambda: {
            "tokens": [
                {
                    "index": 0,
                    "gateway_ready": True,
                    "username": "alice",
                    "user_id": "111111111111111111",
                    "channels": ["222222222222222222"],
                    "guild_id": "333333333333333333",
                    "self_mute": False,
                    "self_deaf": True,
                    "streaming": True,
                    "video": False,
                },
                {
                    "index": 1,
                    "gateway_ready": False,
                    "username": None,
                    "user_id": None,
                },
            ]
        },
    )

    result = await service.get_tokens()

    assert calls == []
    assert result["removed"] == 0
    assert result["tokens"][0]["alive"] is True
    assert result["tokens"][0]["gateway_ready"] is True
    assert result["tokens"][0]["username"] == "alice"
    assert result["tokens"][0]["channels"] == ["222222222222222222"]
    assert result["tokens"][0]["guild_id"] == "333333333333333333"
    assert result["tokens"][0]["self_mute"] is False
    assert result["tokens"][0]["self_deaf"] is True
    assert result["tokens"][0]["streaming"] is True
    assert result["tokens"][0]["video"] is False
    assert result["tokens"][0]["avatar_url"].startswith(
        "https://cdn.discordapp.com/embed/avatars/"
    )
    assert result["tokens"][1]["alive"] is True
    assert result["tokens"][1]["gateway_ready"] is False
    assert result["tokens"][1]["error"] is None

