"""Chrome client identity for dashboard REST calls to Discord.

Discord treats a user token presented by a raw Python HTTP client as a
self-bot signal. The bot writes its live (dpy-self synced) identity into
``bot_status.json``; use it when available, otherwise fall back to a
realistic Chrome fingerprint.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path

STATUS_PATH = Path(__file__).resolve().parent / "bot_status.json"

CLIENT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CLIENT_LOCALE = "en-US"
CLIENT_TIMEZONE = "Asia/Ho_Chi_Minh"
CLIENT_BUILD_NUMBER = 260000
CLIENT_BROWSER_VERSION = "120.0.0.0"
CLIENT_VERSION = "0.0.0"

_LAUNCH_ID = str(uuid.uuid4())
_LAUNCH_SIGNATURE = str(uuid.uuid4())
_HEARTBEAT_SESSION_ID = f"session_{uuid.uuid4().hex[:16]}"

# Per-token client identifiers. Sharing one launch id across accounts is the
# exact signal that got accounts flagged, so each token gets its own stable
# set. Keys are token hashes; the token itself is never stored.
_IDENTITIES: dict[str, dict[str, str]] = {}


def _identity_for(token: str) -> dict[str, str]:
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    identity = _IDENTITIES.get(key)
    if identity is None:
        identity = {
            "client_launch_id": str(uuid.uuid4()),
            "launch_signature": str(uuid.uuid4()),
            "client_heartbeat_session_id": f"session_{uuid.uuid4().hex[:16]}",
        }
        _IDENTITIES[key] = identity
    return identity


def _static_properties() -> dict:
    return {
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": CLIENT_LOCALE,
        "browser_user_agent": CLIENT_USER_AGENT,
        "browser_version": CLIENT_BROWSER_VERSION,
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": CLIENT_BUILD_NUMBER,
        "client_event_source": None,
        "client_version": CLIENT_VERSION,
        "client_launch_id": _LAUNCH_ID,
        "launch_signature": _LAUNCH_SIGNATURE,
        "client_heartbeat_session_id": _HEARTBEAT_SESSION_ID,
        "has_client_mods": False,
        "search_engine": "",
        "search_engine_current": "",
    }


def _encoded(properties: dict) -> str:
    raw = json.dumps(properties, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _live_identity() -> tuple[str, str]:
    """Return ``(user_agent, encoded_super_properties)`` from the bot status."""

    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return CLIENT_USER_AGENT, _encoded(_static_properties())

    user_agent = data.get("client_user_agent")
    encoded = data.get("client_super_properties")
    if isinstance(user_agent, str) and user_agent.strip():
        if isinstance(encoded, str) and encoded.strip():
            return user_agent, encoded
    return CLIENT_USER_AGENT, _encoded(_static_properties())


def _properties_for(
    user_agent: str, encoded: str, token: str | None
) -> dict:
    try:
        properties = json.loads(base64.b64decode(encoded))
        if not isinstance(properties, dict):
            raise ValueError("properties must be an object")
    except Exception:
        properties = _static_properties()
    properties["browser_user_agent"] = user_agent
    if token:
        properties.update(_identity_for(token))
    return properties


def discord_headers(token: str | None = None) -> dict[str, str]:
    """Headers that make dashboard REST calls look like the web client.

    ``token`` scopes the launch identifiers per account; omit it for calls
    that do not belong to a specific user token.
    """

    user_agent, super_properties = _live_identity()
    if token:
        super_properties = _encoded(
            _properties_for(user_agent, super_properties, token)
        )
    return {
        "User-Agent": user_agent,
        "X-Super-Properties": super_properties,
        "X-Discord-Locale": CLIENT_LOCALE,
        "X-Discord-Timezone": CLIENT_TIMEZONE,
        "Accept-Language": f"{CLIENT_LOCALE},en;q=0.9",
    }
