import json
import time

from dashboard.backend.bot_adapter import LiveBotAdapter


def write_status(path, updated_at=None, **overrides):
    data = {
        "state": "online",
        "username": "alice",
        "user_id": "1",
        "latency_ms": 42,
        "uptime_seconds": 10,
        "guild_count": 2,
        "updated_at": time.time() if updated_at is None else updated_at,
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_get_status_online_when_status_file_is_fresh(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)

    status = LiveBotAdapter(path).get_status()

    assert status["state"] == "online"
    assert status["username"] == "alice"
    assert status["guild_count"] == 2


def test_get_status_offline_when_status_file_is_stale(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path, updated_at=time.time() - 120)

    assert LiveBotAdapter(path).get_status()["state"] == "offline"


def test_get_status_offline_when_status_file_is_missing(tmp_path):
    assert LiveBotAdapter(tmp_path / "missing.json").get_status()["state"] == "offline"


def test_get_status_passes_through_sync_fields(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(
        path,
        last_state_sync=1700000000.5,
        sync_errors=3,
        last_error="boom",
    )

    status = LiveBotAdapter(path).get_status()

    assert status["last_state_sync"] == 1700000000.5
    assert status["sync_errors"] == 3
    assert status["last_error"] == "boom"


def test_get_status_sync_fields_default_when_missing(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)

    status = LiveBotAdapter(path).get_status()

    assert status["last_state_sync"] is None
    assert status["sync_errors"] == 0
    assert status["last_error"] is None


def test_get_status_passes_through_last_reload(tmp_path):
    path = tmp_path / "bot_status.json"
    reload_info = {"at": "2026-11-04T00:00:00+00:00", "ok": True, "detail": "Reloaded 8 cogs"}
    write_status(path, last_reload=reload_info)

    assert LiveBotAdapter(path).get_status()["last_reload"] == reload_info


def test_get_status_last_reload_defaults_to_none(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)

    assert LiveBotAdapter(path).get_status()["last_reload"] is None


def test_get_status_passes_through_avatar_url(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path, avatar_url="https://cdn.example/avatar.png")

    status = LiveBotAdapter(path).get_status()

    assert status["avatar_url"] == "https://cdn.example/avatar.png"


def test_get_status_avatar_url_defaults_to_none(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)

    assert LiveBotAdapter(path).get_status()["avatar_url"] is None


def test_offline_adapter_reports_avatar_url_none():
    from dashboard.backend.bot_adapter import OfflineBotAdapter

    assert OfflineBotAdapter().get_status()["avatar_url"] is None


def test_get_status_tolerates_utf8_bom(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    status = LiveBotAdapter(path).get_status()

    assert status["state"] == "online"
    assert status["username"] == "alice"


def test_status_file_with_invalid_utf8_is_treated_as_offline(tmp_path):
    path = tmp_path / "bot_status.json"
    path.write_bytes(b"\xff\xfe\x00\x00")
    adapter = LiveBotAdapter(path)

    assert adapter.get_status()["state"] == "offline"
    assert adapter.can_queue() is False


def test_mutations_are_queued_when_bot_is_online(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path)
    adapter = LiveBotAdapter(path)

    assert adapter.apply_automation({}) == (True, "queued")
    assert adapter.apply_afk({}) == (True, "queued")
    assert adapter.apply_reactions({}) == (True, "queued")


def test_mutations_report_offline_when_bot_is_not_running(tmp_path):
    adapter = LiveBotAdapter(tmp_path / "missing.json")

    assert adapter.apply_automation({}) == (False, "bot_offline")
    assert adapter.apply_afk({}) == (False, "bot_offline")
    assert adapter.apply_reactions({}) == (False, "bot_offline")


def test_can_queue_uses_voice_stale_window(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(path, updated_at=time.time() - 20)
    adapter = LiveBotAdapter(path)

    assert adapter.can_queue() is False
    assert adapter.get_status()["state"] == "online"

    write_status(path)
    assert adapter.can_queue() is True

    assert LiveBotAdapter(tmp_path / "missing.json").can_queue() is False
