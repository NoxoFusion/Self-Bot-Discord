"""Shared Discord client fingerprint for REST and gateway traffic.

Keeping one source of truth avoids the common selfbot tell where the gateway
identifies as Chrome 120 while REST requests send a generic User-Agent.
"""

from __future__ import annotations

import base64
import json
import uuid

CLIENT_BUILD_NUMBER = 260000
CLIENT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CLIENT_LOCALE = "en-US"
CLIENT_TIMEZONE = "Asia/Ho_Chi_Minh"
CLIENT_OS = "Windows"
CLIENT_BROWSER = "Chrome"
CLIENT_DEVICE = ""
CLIENT_OS_VERSION = "10"
CLIENT_BROWSER_VERSION = "120.0.0.0"
CLIENT_RELEASE_CHANNEL = "stable"
CLIENT_VERSION = "0.0.0"

_LAUNCH_ID = str(uuid.uuid4())

# Live identity adopted from discord.py-self at login (it fetches the current
# Chrome version + Discord build number at runtime). When present, every raw
# gateway IDENTIFY and REST call reuses it so all sessions of a token present
# the exact same client fingerprint.
_synced: dict | None = None


def sync_from_headers(headers) -> bool:
    """Adopt dpy-self's live client identity from ``bot.http.headers``.

    Returns ``True`` when the identity was adopted. Safe to call repeatedly
    (e.g. on every reconnect); keeps the last known good values on failure.
    """

    global _synced
    try:
        props = dict(getattr(headers, "super_properties", {}) or {})
        if not props:
            return False
        extra = dict(getattr(headers, "extra_gateway_properties", {}) or {})
        encoded = getattr(headers, "encoded_super_properties", None)
        _synced = {
            "super_properties": props,
            "extra": extra,
            "encoded": encoded if isinstance(encoded, str) and encoded else None,
            "user_agent": props.get("browser_user_agent") or CLIENT_USER_AGENT,
            "build_number": props.get("client_build_number")
            or CLIENT_BUILD_NUMBER,
            "browser_version": props.get("browser_version")
            or CLIENT_BROWSER_VERSION,
        }
        return True
    except Exception:
        return False


def session_identity() -> dict:
    """Fresh per-session identifiers for one gateway/REST client.

    Real clients get one launch id per browser instance; two different accounts
    never share them.  Each voice connector must therefore generate its own set
    instead of reusing the main bot's (or another token's) values.
    """

    return {
        "client_launch_id": str(uuid.uuid4()),
        "launch_signature": str(uuid.uuid4()),
        "client_heartbeat_session_id": f"session_{uuid.uuid4().hex[:16]}",
    }


def _static_properties() -> dict:
    return {
        "os": CLIENT_OS,
        "browser": CLIENT_BROWSER,
        "device": CLIENT_DEVICE,
        "system_locale": CLIENT_LOCALE,
        "browser_user_agent": CLIENT_USER_AGENT,
        "browser_version": CLIENT_BROWSER_VERSION,
        "os_version": CLIENT_OS_VERSION,
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": CLIENT_RELEASE_CHANNEL,
        "client_build_number": CLIENT_BUILD_NUMBER,
        "client_event_source": None,
        "client_version": CLIENT_VERSION,
        "client_launch_id": _LAUNCH_ID,
        "has_client_mods": False,
        "search_engine": "",
        "search_engine_current": "",
    }


def client_properties(session: dict | None = None) -> dict:
    """Properties Discord expects in X-Super-Properties and IDENTIFY.

    ``session`` overrides per-session fields (launch id, signature, heartbeat
    session id) so every connector presents its own browser instance.
    """
    if _synced is not None:
        merged = dict(_synced["super_properties"])
        merged.update(_synced["extra"])
    else:
        merged = _static_properties()

    if session:
        merged.update(session)
    return merged


def super_properties(session: dict | None = None) -> str:
    """Base64-encoded compact JSON for the X-Super-Properties header."""
    if session is None and _synced is not None and _synced.get("encoded"):
        return _synced["encoded"]
    raw = json.dumps(
        client_properties(session), separators=(",", ":")
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def discord_headers(session: dict | None = None) -> dict[str, str]:
    """Headers that should accompany every Discord REST API request."""
    user_agent = (
        _synced["user_agent"] if _synced is not None else CLIENT_USER_AGENT
    )
    return {
        "User-Agent": user_agent,
        "X-Super-Properties": super_properties(session),
        "X-Discord-Locale": CLIENT_LOCALE,
        "X-Discord-Timezone": CLIENT_TIMEZONE,
        "Accept-Language": f"{CLIENT_LOCALE},en;q=0.9",
    }
