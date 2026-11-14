import base64
import json

from dashboard.backend import discord_identity


def test_headers_use_a_chrome_client():
    headers = discord_identity.discord_headers()

    assert "Chrome/" in headers["User-Agent"]
    assert "Python" not in headers["User-Agent"]
    assert headers["X-Discord-Locale"] == "en-US"
    props = json.loads(base64.b64decode(headers["X-Super-Properties"]))
    assert props["browser"] == "Chrome"
    assert props["client_launch_id"]
    assert props["launch_signature"]


def test_headers_prefer_the_bot_live_identity(tmp_path, monkeypatch):
    path = tmp_path / "bot_status.json"
    path.write_text(
        json.dumps(
            {
                "client_user_agent": "UA-LIVE",
                "client_super_properties": "ENCODED",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(discord_identity, "STATUS_PATH", path)

    headers = discord_identity.discord_headers()

    assert headers["User-Agent"] == "UA-LIVE"
    assert headers["X-Super-Properties"] == "ENCODED"


def test_headers_are_scoped_per_token():
    first = json.loads(
        base64.b64decode(
            discord_identity.discord_headers("token-a")["X-Super-Properties"]
        )
    )
    second = json.loads(
        base64.b64decode(
            discord_identity.discord_headers("token-b")["X-Super-Properties"]
        )
    )
    again = json.loads(
        base64.b64decode(
            discord_identity.discord_headers("token-a")["X-Super-Properties"]
        )
    )

    assert first["client_launch_id"] != second["client_launch_id"]
    assert again["client_launch_id"] == first["client_launch_id"]


def test_headers_fall_back_when_status_is_invalid(tmp_path, monkeypatch):
    path = tmp_path / "bot_status.json"
    path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(discord_identity, "STATUS_PATH", path)

    headers = discord_identity.discord_headers()

    assert "Chrome/" in headers["User-Agent"]
