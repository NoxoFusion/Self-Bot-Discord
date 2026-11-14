"""aiohttp application for the local dashboard API."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from aiohttp import web

from .auth import (
    AuthManager,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    csrf_matches,
    generate_pairing_code,
)
from .bot_adapter import BotAdapter, OfflineBotAdapter
from .clone_queue import CloneCommandQueue, CloneResultStore
from .config import (
    DEFAULT_CONFIG,
    add_root_voice_token,
    delete_root_voice_token,
    get_root_prefix,
    load_config,
    load_root_bot_token,
    load_root_voice_tokens,
    request_bot_reload,
    set_root_prefix,
)
from .discord_profile import DiscordProfileService
from .emoji_queue import EmojiCommandQueue, EmojiResultStore
from .state_store import StateStore
from .utility import UtilityError, fetch_weather, image_result
from .voice import (
    SoundboardService,
    TokenProfileStore,
    VoiceCommandQueue,
    VoiceError,
    VoiceTokenService,
    _avatar_url,
    fetch_discord_json,
    read_voice_state,
)
from .voice_api import (
    protected_mutation_paths as voice_protected_mutation_paths,
    protected_paths as voice_protected_paths,
    register_voice_api,
)

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_API_PORT = 8765

FEATURES: dict[str, bool] = {
    "automation": True,
    "afk": True,
    "reactions": True,
    "voice": True,
    "utility": True,
    "moderation": False,
}

CAPABILITIES: list[dict[str, str]] = [
    {
        "id": "automation",
        "label": "Auto-Mess",
        "status": "available",
        "reason": "",
    },
    {"id": "afk", "label": "AFK", "status": "available", "reason": ""},
    {
        "id": "reactions",
        "label": "Auto-Reactions",
        "status": "available",
        "reason": "",
    },
    {
        "id": "voice",
        "label": "Voice",
        "status": "available",
        "reason": "",
    },
    {
        "id": "utility",
        "label": "Utility",
        "status": "available",
        "reason": "",
    },
    {
        "id": "moderation",
        "label": "Moderation",
        "status": "needs_config",
        "reason": "Not implemented in this build",
    },
    {
        "id": "presence",
        "label": "Presence",
        "status": "unsupported",
        "reason": "User presence spoofing is not supported for application bots",
    },
]

PROTECTED_PATHS = {
    "/api/v1/status",
    "/api/v1/capabilities",
    "/api/v1/automation",
    "/api/v1/afk",
    "/api/v1/reactions",
    "/api/v1/utility/weather",
    "/api/v1/utility/image",
    "/api/v1/utility/emoji-copy",
    "/api/v1/utility/emoji-copy/status",
    "/api/v1/utility/clone",
    "/api/v1/utility/clone/status",
    "/api/v1/voice/soundboard",
    "/api/v1/voice/soundboard/defaults",
    "/api/v1/settings",
    "/api/v1/logout",
}
# GET on /voice/tokens is intentionally public (existing dashboard behaviour),
# but token mutations and voice control actions must require a session and CSRF.
PROTECTED_MUTATION_PATHS = {
    "/api/v1/voice/tokens",
    "/api/v1/voice/join",
    "/api/v1/voice/leave",
    "/api/v1/voice/stream",
    "/api/v1/voice/camera",
    "/api/v1/voice/soundboard/play",
    "/api/v1/voice/search",
    "/api/v1/voice/audio/filters",
    "/api/v1/voice/audio/volume",
    "/api/v1/voice/audio/forcefix",
    "/api/v1/voice/audio/loop",
    "/api/v1/voice/audio/replay",
    "/api/v1/settings/prefix",
    "/api/v1/settings/reload",
}
CSRF_EXEMPT_PATHS = {"/api/v1/pair"}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_DIGITS_RE = re.compile(r"^[0-9]+$")


def _app_key(name: str, value_type: type) -> Any:
    """Use typed aiohttp AppKeys when available, strings on older versions."""
    factory = getattr(web, "AppKey", None)
    return factory(name, value_type) if factory is not None else name


def _request_key(name: str, value_type: type) -> Any:
    """Use typed aiohttp RequestKeys when available, strings otherwise."""
    factory = getattr(web, "RequestKey", None)
    return factory(name, value_type) if factory is not None else name


CONFIG_KEY = _app_key("config", dict)
STATE_STORE_KEY = _app_key("state_store", StateStore)
ADAPTER_KEY = _app_key("adapter", BotAdapter)
PROFILE_SERVICE_KEY = _app_key("profile_service", object)
VOICE_SERVICE_KEY = _app_key("voice_service", object)
TOKEN_PROFILE_STORE_KEY = _app_key("token_profile_store", object)
TOKEN_PROFILE_WARMUP_KEY = _app_key("token_profile_warmup", object)
SOUNDBOARD_SERVICE_KEY = _app_key("soundboard_service", object)
VOICE_COMMAND_QUEUE_KEY = _app_key("voice_command_queue", object)
VOICE_STATE_PATH_KEY = _app_key("voice_state_path", Path)
CLONE_QUEUE_KEY = _app_key("clone_queue", object)
CLONE_RESULTS_KEY = _app_key("clone_results", object)
EMOJI_QUEUE_KEY = _app_key("emoji_queue", object)
VOICE_PROTECTED_PATHS_KEY = _app_key("voice_protected_paths", set)
VOICE_PROTECTED_MUTATION_PATHS_KEY = _app_key("voice_protected_mutation_paths", set)
EMOJI_RESULTS_KEY = _app_key("emoji_results", object)
AUTH_KEY = _app_key("auth", AuthManager)
ALLOWED_HOSTS_KEY = _app_key("allowed_hosts", set)
ALLOWED_ORIGINS_KEY = _app_key("allowed_origins", set)
STARTED_AT_KEY = _app_key("started_at", float)
MAIN_ACCOUNT_ID_KEY = _app_key("main_account_id", dict)
SESSION_KEY = _request_key("session", dict)
SESSION_TOKEN_KEY = _request_key("session_token", str)


def _default_allowed_hosts(config: dict[str, Any]) -> set[str]:
    hosts = {
        "127.0.0.1:8765",
        "localhost:8765",
        "127.0.0.1:4000",
        "localhost:4000",
    }
    port = config.get("api_port", DEFAULT_API_PORT)
    if isinstance(port, int) and not isinstance(port, bool):
        hosts.add(f"127.0.0.1:{port}")
        hosts.add(f"localhost:{port}")
    return hosts


@web.middleware
async def cors_middleware(
    request: web.Request, handler: Callable[[web.Request], Any]
) -> web.StreamResponse:
    """Allow only the configured local dashboard origin, with credentials."""
    origin = request.headers.get("Origin")
    allowed = request.app[ALLOWED_ORIGINS_KEY]

    if request.method == "OPTIONS":
        if origin in allowed:
            response = web.Response(status=204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-CSRF-Token"
            )
            response.headers["Vary"] = "Origin"
            return response
        return web.Response(status=403)

    response = await handler(request)
    if origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


@web.middleware
async def security_middleware(
    request: web.Request, handler: Callable[[web.Request], Any]
) -> web.StreamResponse:
    """Reject requests whose Host/Origin are not explicitly allowed."""
    host = request.headers.get("Host", "").lower()
    if host not in request.app[ALLOWED_HOSTS_KEY]:
        return web.json_response({"error": "forbidden_host"}, status=403)

    origin = request.headers.get("Origin")
    if origin is not None and origin not in request.app[ALLOWED_ORIGINS_KEY]:
        return web.json_response({"error": "forbidden_origin"}, status=403)

    return await handler(request)


@web.middleware
async def auth_middleware(
    request: web.Request, handler: Callable[[web.Request], Any]
) -> web.StreamResponse:
    """Attach the session and enforce auth/CSRF on protected API routes."""
    token = request.cookies.get(SESSION_COOKIE)
    session = request.app[AUTH_KEY].get_session(token)
    request[SESSION_KEY] = session
    request[SESSION_TOKEN_KEY] = token if session is not None else None

    voice_paths = (
        request.app[VOICE_PROTECTED_PATHS_KEY]
        if VOICE_PROTECTED_PATHS_KEY in request.app
        else set()
    )
    voice_mutation_paths = (
        request.app[VOICE_PROTECTED_MUTATION_PATHS_KEY]
        if VOICE_PROTECTED_MUTATION_PATHS_KEY in request.app
        else set()
    )
    protected = (
        request.path in PROTECTED_PATHS
        or request.path in voice_paths
        or (
            (
                request.path in PROTECTED_MUTATION_PATHS
                or request.path in voice_mutation_paths
            )
            and request.method in MUTATING_METHODS
        )
    )
    if protected:
        if session is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        if (
            request.method in MUTATING_METHODS
            and request.path not in CSRF_EXEMPT_PATHS
        ):
            supplied = request.headers.get("X-CSRF-Token")
            if not csrf_matches(session, supplied):
                return web.json_response({"error": "csrf_failed"}, status=403)

    return await handler(request)


async def _read_json(request: web.Request) -> Any:
    """Return a parsed JSON body, or ``None`` for a missing/malformed body."""
    try:
        return await request.json()
    except Exception:  # malformed JSON or an unsupported body encoding
        return None


def _validation_error(details: list[str]) -> web.Response:
    return web.json_response(
        {"error": "validation_error", "details": details},
        status=400,
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_digits(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGITS_RE.fullmatch(value))


def _is_digits_or_empty(value: Any) -> bool:
    return isinstance(value, str) and (
        value == "" or bool(_DIGITS_RE.fullmatch(value))
    )


def _token_index_error(token_index: int) -> str | None:
    """Return a validation message when ``token_index`` is not configured.

    The bot silently drops commands for indexes outside its ``voice_token``
    pool, so reject them here instead of reporting ``queued`` for a command
    that will never run.  An empty or unreadable pool rejects every index.
    """

    tokens = load_root_voice_tokens()
    if token_index >= len(tokens) or not tokens[token_index].strip():
        return "token_index is not configured"
    return None


def validate_utility_weather(
    body: Any,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]
    location = body.get("location")
    if not isinstance(location, str) or not 1 <= len(location.strip()) <= 200:
        return None, ["location must be a string of 1-200 characters"]
    return {"location": location.strip()}, []


def validate_utility_image(
    body: Any,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 500:
        return None, ["prompt must be a string of 1-500 characters"]
    return {"prompt": prompt.strip()}, []


def validate_utility_emoji_copy(
    body: Any,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]

    errors: list[str] = []
    source_id = body.get("source_id")
    target_id = body.get("target_id")
    emoji_ids_raw = body.get("emoji_ids", [])

    if not _is_digits(source_id):
        errors.append("source_id must be a string of digits")
    if not _is_digits(target_id):
        errors.append("target_id must be a string of digits")
    if _is_digits(source_id) and source_id == target_id:
        errors.append("source_id and target_id must be different")

    emoji_ids: list[str] = []
    if not isinstance(emoji_ids_raw, list):
        errors.append("emoji_ids must be a list")
    elif len(emoji_ids_raw) > 100:
        errors.append("emoji_ids must contain at most 100 items")
    else:
        for index, emoji_id in enumerate(emoji_ids_raw):
            if not _is_digits(emoji_id):
                errors.append(f"emoji_ids[{index}] must be a string of digits")
            else:
                emoji_ids.append(emoji_id)

    if errors:
        return None, errors
    return (
        {
            "source_id": source_id,
            "target_id": target_id,
            "emoji_ids": emoji_ids,
        },
        [],
    )


def validate_utility_clone(
    body: Any,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]

    errors: list[str] = []
    source_id = body.get("source_id")
    target_id = body.get("target_id")
    confirm = body.get("confirm")
    options_raw = body.get("options")

    if not _is_digits(source_id):
        errors.append("source_id must be a string of digits")
    if not _is_digits(target_id):
        errors.append("target_id must be a string of digits")
    if _is_digits(source_id) and source_id == target_id:
        errors.append("source_id and target_id must be different")
    if confirm is not True:
        errors.append("confirm must be true")

    options = {"info": True, "structure": True, "emojis": False}
    if options_raw is not None:
        if not isinstance(options_raw, dict):
            errors.append("options must be an object")
        else:
            for key in ("info", "structure", "emojis"):
                value = options_raw.get(key, False)
                if not isinstance(value, bool):
                    errors.append(f"options.{key} must be a boolean")
                else:
                    options[key] = value
            if not any(options.values()):
                errors.append("at least one clone option must be true")

    if errors:
        return None, errors
    return {
        "source_id": source_id,
        "target_id": target_id,
        "options": options,
    }, []


def validate_automation(
    body: Any,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Validate and normalize an automation payload."""
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]

    errors: list[str] = []

    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")

    triggers_raw = body.get("triggers")
    triggers: list[dict[str, str]] = []
    if not isinstance(triggers_raw, list):
        errors.append("triggers must be a list")
    elif len(triggers_raw) > 5:
        errors.append("triggers must contain at most 5 items")
    else:
        for index, trigger in enumerate(triggers_raw):
            if not isinstance(trigger, dict):
                errors.append(f"triggers[{index}] must be an object")
                continue

            keyword = trigger.get("keyword")
            reply = trigger.get("reply")
            item_ok = True
            if not isinstance(keyword, str) or not 1 <= len(keyword) <= 100:
                errors.append(
                    f"triggers[{index}].keyword must be a string of 1-100 characters"
                )
                item_ok = False
            if not isinstance(reply, str) or not 1 <= len(reply) <= 500:
                errors.append(
                    f"triggers[{index}].reply must be a string of 1-500 characters"
                )
                item_ok = False
            if item_ok:
                triggers.append({"keyword": keyword, "reply": reply})

    broadcaster_raw = body.get("broadcaster")
    broadcaster: dict[str, Any] = {}
    if not isinstance(broadcaster_raw, dict):
        errors.append("broadcaster must be an object")
    else:
        broadcaster_enabled = broadcaster_raw.get("enabled")
        mode = broadcaster_raw.get("mode")
        if mode == "count":
            # Legacy dashboard label — the cog implements this as "message".
            mode = "message"
        value = broadcaster_raw.get("value")
        channel_id = broadcaster_raw.get("channel_id")
        broadcaster_ok = True

        if not isinstance(broadcaster_enabled, bool):
            errors.append("broadcaster.enabled must be a boolean")
            broadcaster_ok = False
        if mode not in ("time", "message"):
            errors.append("broadcaster.mode must be 'time' or 'message'")
            broadcaster_ok = False
        if not _is_int(value):
            errors.append("broadcaster.value must be an integer")
            broadcaster_ok = False
        elif mode == "time" and not 30 <= value <= 86400:
            errors.append(
                "broadcaster.value must be between 30 and 86400 when mode is 'time'"
            )
            broadcaster_ok = False
        elif mode == "message" and not 1 <= value <= 50:
            errors.append(
                "broadcaster.value must be between 1 and 50 when mode is 'message'"
            )
            broadcaster_ok = False
        if not _is_digits_or_empty(channel_id):
            errors.append(
                "broadcaster.channel_id must be a string of digits or empty"
            )
            broadcaster_ok = False

        if broadcaster_ok:
            broadcaster = {
                "enabled": broadcaster_enabled,
                "mode": mode,
                "value": value,
                "channel_id": channel_id,
            }

    pool_raw = body.get("pool")
    pool: list[str] = []
    if not isinstance(pool_raw, list):
        errors.append("pool must be a list")
    elif len(pool_raw) > 5:
        errors.append("pool must contain at most 5 items")
    else:
        for index, item in enumerate(pool_raw):
            if not isinstance(item, str) or not 1 <= len(item) <= 500:
                errors.append(
                    f"pool[{index}] must be a string of 1-500 characters"
                )
            else:
                pool.append(item)

    if errors:
        return None, errors

    return (
        {
            "enabled": enabled,
            "triggers": triggers,
            "broadcaster": broadcaster,
            "pool": pool,
        },
        [],
    )


def validate_afk(body: Any) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Validate and normalize an AFK payload."""
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]

    errors: list[str] = []
    enabled = body.get("enabled")
    reason = body.get("reason")
    cooldown = body.get("cooldown", 10)
    reply_mentions = body.get("reply_mentions", True)
    reply_dms = body.get("reply_dms", True)

    if not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")
    if not isinstance(reason, str):
        errors.append("reason must be a string")
    elif len(reason) > 200:
        errors.append("reason must be at most 200 characters")
    elif enabled is True and not reason.strip():
        errors.append("reason is required when AFK is enabled")
    if not _is_int(cooldown) or not 3 <= cooldown <= 60:
        errors.append("cooldown must be an integer between 3 and 60")
    if not isinstance(reply_mentions, bool):
        errors.append("reply_mentions must be a boolean")
    if not isinstance(reply_dms, bool):
        errors.append("reply_dms must be a boolean")

    if errors:
        return None, errors
    return (
        {
            "enabled": enabled,
            "reason": reason,
            "cooldown": cooldown,
            "reply_mentions": reply_mentions,
            "reply_dms": reply_dms,
        },
        [],
    )


def validate_reactions(body: Any) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Validate and normalize a reactions payload."""
    if not isinstance(body, dict):
        return None, ["Request body must be a JSON object"]

    errors: list[str] = []
    enabled = body.get("enabled")
    target = body.get("target")
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    emojis_raw = body.get("emojis")
    cooldown_raw = body.get("cooldown", 3)

    if not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")
    if target not in ("user", "everyone"):
        errors.append("target must be 'user' or 'everyone'")

    cooldown = 3
    if cooldown_raw is None:
        cooldown_raw = 3
    if isinstance(cooldown_raw, bool) or not isinstance(
        cooldown_raw, (int, float)
    ):
        errors.append("cooldown must be a number between 1 and 30")
    elif not 1 <= cooldown_raw <= 30:
        errors.append("cooldown must be between 1 and 30 seconds")
    else:
        cooldown = int(cooldown_raw)

    if not isinstance(user_id, str):
        errors.append("user_id must be a string")
    elif target == "user" and enabled is True and not _is_digits(user_id):
        errors.append(
            "user_id must be a string of digits when target is 'user' and enabled"
        )

    if not _is_digits_or_empty(channel_id):
        errors.append("channel_id must be a string of digits or empty")
    elif target == "everyone" and enabled is True and not _is_digits(channel_id):
        errors.append(
            "channel_id is required when target is 'everyone' — "
            "reacting in every channel gets accounts flagged"
        )

    emojis: list[str] = []
    if not isinstance(emojis_raw, list):
        errors.append("emojis must be a list")
    elif len(emojis_raw) > 10:
        errors.append("emojis must contain at most 10 items")
    else:
        for index, emoji in enumerate(emojis_raw):
            if not isinstance(emoji, str) or not emoji:
                errors.append(f"emojis[{index}] must be a non-empty string")
            else:
                emojis.append(emoji)
        if enabled is True and not emojis:
            errors.append("emojis must contain at least 1 item when enabled")

    if errors:
        return None, errors

    return (
        {
            "enabled": enabled,
            "target": target,
            "user_id": user_id,
            "channel_id": channel_id,
            "emojis": emojis,
            "cooldown": cooldown,
        },
        [],
    )


async def pair(request: web.Request) -> web.Response:
    auth: AuthManager = request.app[AUTH_KEY]
    remote_ip = request.remote or "unknown"

    if not auth.allow_pair_attempt(remote_ip):
        return web.json_response({"error": "rate_limited"}, status=429)

    body = await _read_json(request)
    code = body.get("code") if isinstance(body, dict) else None
    if not auth.verify_pairing_code(code):
        return web.json_response({"error": "invalid_code"}, status=401)

    token, csrf = auth.create_session()
    response = web.json_response({"authenticated": True, "csrf_token": csrf})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="Strict",
        path="/",
    )
    return response


async def get_session(request: web.Request) -> web.Response:
    session = request.get(SESSION_KEY)
    if session is None:
        return web.json_response({"authenticated": False}, status=401)
    return web.json_response(
        {"authenticated": True, "csrf_token": session["csrf"]}
    )


async def logout(request: web.Request) -> web.Response:
    request.app[AUTH_KEY].delete_session(request.get(SESSION_TOKEN_KEY))
    response = web.Response(status=204)
    response.del_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="Strict",
    )
    return response


async def get_status(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    profile_service = request.app[PROFILE_SERVICE_KEY]
    bot_status = dict(request.app[ADAPTER_KEY].get_status())

    if profile_service is not None and not bot_status.get("username"):
        profile = await profile_service.get()
        if profile:
            bot_status.update(profile)

    if not (
        config.get("bot_token")
        or (
            profile_service is not None
            and getattr(profile_service, "configured", False)
        )
    ):
        warnings = ["Bot token not configured"]
    elif isinstance(request.app[ADAPTER_KEY], OfflineBotAdapter):
        warnings = ["Live bot adapter not implemented in this build"]
    elif bot_status.get("state") != "online":
        warnings = ["Bot is offline — start the bot process"]
    else:
        warnings = []

    payload = {
        "bot": bot_status,
        "api": {
            "version": API_VERSION,
            "uptime_seconds": int(
                time.monotonic() - request.app[STARTED_AT_KEY]
            ),
        },
        "features": dict(FEATURES),
        "warnings": warnings,
    }
    return web.json_response(payload)


async def get_capabilities(request: web.Request) -> web.Response:
    return web.json_response(
        {"features": [dict(feature) for feature in CAPABILITIES]}
    )


async def get_settings(request: web.Request) -> web.Response:
    profile_service = request.app[PROFILE_SERVICE_KEY]
    profile = (
        await profile_service.get() if profile_service is not None else None
    )
    return web.json_response(
        {"prefix": get_root_prefix(), "profile": profile}
    )


async def put_settings_prefix(request: web.Request) -> web.Response:
    body = await _read_json(request)
    prefix = body.get("prefix") if isinstance(body, dict) else None
    cleaned = prefix.strip() if isinstance(prefix, str) else ""

    if (
        not isinstance(prefix, str)
        or not cleaned
        or len(cleaned) > 5
        or any(char.isspace() for char in cleaned)
    ):
        return web.json_response(
            {"saved": False, "error": "invalid_prefix"},
            status=400,
        )

    if not set_root_prefix(cleaned):
        return web.json_response(
            {"saved": False, "error": "config_write_failed"},
            status=500,
        )

    if not request_bot_reload():
        return web.json_response(
            {"error": "reload_request_failed"},
            status=500,
        )
    return web.json_response(
        {"saved": True, "prefix": cleaned, "reload_requested": True}
    )


async def post_settings_reload(request: web.Request) -> web.Response:
    if not request_bot_reload():
        return web.json_response(
            {"error": "reload_request_failed"},
            status=500,
        )
    return web.json_response({"requested": True})


async def get_automation(request: web.Request) -> web.Response:
    state = await request.app[STATE_STORE_KEY].load()
    return web.json_response(state["automation"])


async def put_automation(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_automation(body)
    if errors:
        return _validation_error(errors)

    state = await request.app[STATE_STORE_KEY].update(
        lambda current: {**current, "automation": data}
    )
    applied, reason = request.app[ADAPTER_KEY].apply_automation(data)
    return web.json_response(
        {
            "saved": True,
            "applied": applied,
            "reason": reason,
            "data": state["automation"],
        }
    )


async def get_afk(request: web.Request) -> web.Response:
    state = await request.app[STATE_STORE_KEY].load()
    return web.json_response(state["afk"])


async def put_afk(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_afk(body)
    if errors:
        return _validation_error(errors)

    state = await request.app[STATE_STORE_KEY].update(
        lambda current: {**current, "afk": data}
    )
    applied, reason = request.app[ADAPTER_KEY].apply_afk(data)
    return web.json_response(
        {
            "saved": True,
            "applied": applied,
            "reason": reason,
            "data": state["afk"],
        }
    )


async def get_reactions(request: web.Request) -> web.Response:
    state = await request.app[STATE_STORE_KEY].load()
    return web.json_response(state["reactions"])


async def put_reactions(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_reactions(body)
    if errors:
        return _validation_error(errors)

    state = await request.app[STATE_STORE_KEY].update(
        lambda current: {**current, "reactions": data}
    )
    applied, reason = request.app[ADAPTER_KEY].apply_reactions(data)
    return web.json_response(
        {
            "saved": True,
            "applied": applied,
            "reason": reason,
            "data": state["reactions"],
        }
    )


async def post_utility_weather(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_utility_weather(body)
    if errors:
        return _validation_error(errors)

    try:
        result = await fetch_weather(data["location"])
    except UtilityError as exc:
        status = 400 if exc.code == "location_not_found" else 502
        return web.json_response({"error": exc.code}, status=status)
    return web.json_response({"ok": True, "data": result})


async def post_utility_image(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_utility_image(body)
    if errors:
        return _validation_error(errors)
    return web.json_response({"ok": True, "data": image_result(data["prompt"])})


def _bot_offline_error(request: web.Request) -> web.Response | None:
    """Return a 503 when the adapter reports the bot cannot queue commands."""

    checker = getattr(request.app[ADAPTER_KEY], "can_queue", None)
    if callable(checker):
        try:
            online = bool(checker())
        except Exception:
            logger.exception("Bot liveness check failed")
            online = False
        if not online:
            return web.json_response({"error": "bot_offline"}, status=503)
    return None


async def post_utility_emoji_copy(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_utility_emoji_copy(body)
    if errors:
        return _validation_error(errors)

    queue = request.app[EMOJI_QUEUE_KEY]
    if queue is not None:
        offline = _bot_offline_error(request)
        if offline is not None:
            return offline
        request_id = EmojiCommandQueue.new_request_id()
        queue.enqueue(
            {
                "request_id": request_id,
                "source_id": data["source_id"],
                "target_id": data["target_id"],
                "emoji_ids": data["emoji_ids"],
            }
        )
        return web.json_response({"queued": True, "request_id": request_id})

    applied, reason, result = request.app[ADAPTER_KEY].run_utility(
        "emoji_copy", data
    )
    return web.json_response(
        {
            "applied": applied,
            "reason": reason,
            "data": data,
            "result": result,
        }
    )


async def get_utility_emoji_copy_status(request: web.Request) -> web.Response:
    results = request.app[EMOJI_RESULTS_KEY]
    request_id = (request.query.get("request_id") or "").strip()
    if not request_id:
        return _validation_error(["request_id is required"])
    if results is None:
        return web.json_response({"error": "not_found"}, status=404)

    result = results.read(request_id)
    if result is None:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response(result)


async def post_utility_clone(request: web.Request) -> web.Response:
    body = await _read_json(request)
    data, errors = validate_utility_clone(body)
    if errors:
        return _validation_error(errors)

    queue = request.app[CLONE_QUEUE_KEY]
    if queue is not None:
        offline = _bot_offline_error(request)
        if offline is not None:
            return offline
        request_id = CloneCommandQueue.new_request_id()
        queue.enqueue(
            {
                "request_id": request_id,
                "source_id": data["source_id"],
                "target_id": data["target_id"],
                "options": data["options"],
            }
        )
        return web.json_response({"queued": True, "request_id": request_id})

    applied, reason, result = request.app[ADAPTER_KEY].run_utility(
        "clone", data
    )
    return web.json_response(
        {
            "applied": applied,
            "reason": reason,
            "data": data,
            "result": result,
        }
    )


async def get_utility_clone_status(request: web.Request) -> web.Response:
    results = request.app[CLONE_RESULTS_KEY]
    request_id = (request.query.get("request_id") or "").strip()
    if not request_id:
        return _validation_error(["request_id is required"])
    if results is None:
        return web.json_response({"error": "not_found"}, status=404)

    result = results.read(request_id)
    if result is None:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response(result)


async def get_voice_tokens(request: web.Request) -> web.Response:
    service = request.app[VOICE_SERVICE_KEY]
    if service is None:
        return web.json_response(
            {"tokens": [], "removed": 0, "state_updated_at": None}
        )

    payload = await service.get_tokens()
    state = read_voice_state(request.app[VOICE_STATE_PATH_KEY])
    state_by_index = {
        str(item.get("index")): item
        for item in state.get("tokens", [])
        if isinstance(item, dict)
    }

    for token in payload.get("tokens", []):
        state_token = state_by_index.get(str(token.get("index")), {})
        channels = state_token.get("channels")
        token["channels"] = channels if isinstance(channels, list) else []
        token["guild_id"] = state_token.get("guild_id")
        token["gateway_ready"] = bool(state_token.get("gateway_ready"))
        token["streaming"] = bool(state_token.get("streaming"))
        token["video"] = bool(state_token.get("video"))
        token["self_mute"] = bool(state_token.get("self_mute", True))
        token["self_deaf"] = bool(state_token.get("self_deaf", False))
        token["audio_active"] = bool(state_token.get("audio_active"))
        token["audio_playing"] = bool(state_token.get("audio_playing"))
        guild_channels = state_token.get("guild_channels")
        token["guild_channels"] = (
            guild_channels if isinstance(guild_channels, dict) else {}
        )

    profile_store = request.app[TOKEN_PROFILE_STORE_KEY]
    if profile_store is not None:
        for token in payload.get("tokens", []):
            profile_store.apply(token.get("index"), token)

    payload["state_updated_at"] = state.get("updated_at")
    return web.json_response(payload)


def _voice_token_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Build the public token summary returned after validation."""
    user_id = str(data.get("id") or "")
    username = data.get("username")
    display_name = data.get("global_name") or username
    avatar_hash = data.get("avatar")
    return {
        "username": username,
        "display_name": display_name,
        "user_id": user_id,
        "avatar_url": _avatar_url(
            user_id,
            avatar_hash if isinstance(avatar_hash, str) else None,
        ),
    }


async def _resolve_main_user_id(
    request: web.Request, main_token: str
) -> str | None:
    """Return the main account id, falling back to the configured token.

    The live status is authoritative while the bot is online.  When the bot is
    offline its status has no ``user_id``, so resolve the id from the configured
    main token once and cache it on the application.  A missing token or a
    failed lookup leaves the guard disabled instead of blocking every token.
    """

    try:
        status_user_id = request.app[ADAPTER_KEY].get_status().get("user_id")
    except Exception:
        status_user_id = None
    if status_user_id:
        return str(status_user_id)

    if not main_token:
        logger.warning(
            "Main account id is unavailable: bot is offline and no main "
            "token is configured"
        )
        return None

    fingerprint = hashlib.sha256(main_token.encode("utf-8")).hexdigest()
    cached = request.app.get(MAIN_ACCOUNT_ID_KEY)
    if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
        cached_user_id = cached.get("user_id")
        if cached_user_id:
            return str(cached_user_id)

    status, data = await fetch_discord_json(main_token, "GET", "/users/@me")
    user_id = (
        data.get("id") if status == 200 and isinstance(data, dict) else None
    )
    if not user_id:
        logger.warning(
            "Could not resolve the main account id from the configured "
            "token (%s)",
            f"http_{status}" if status is not None else "network_error",
        )
        return None

    user_id = str(user_id)
    cache = request.app.get(MAIN_ACCOUNT_ID_KEY)
    if not isinstance(cache, dict):
        cache = {}
        request.app[MAIN_ACCOUNT_ID_KEY] = cache
    cache["fingerprint"] = fingerprint
    cache["user_id"] = user_id
    return user_id


async def post_voice_token(request: web.Request) -> web.Response:
    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token = body.get("token")
    if not isinstance(token, str) or not token.strip():
        return _validation_error(["token must be a non-empty string"])
    token = token.strip()

    status, data = await fetch_discord_json(token, "GET", "/users/@me")
    if status is None:
        return web.json_response({"error": "network_error"}, status=502)
    if status == 401:
        return web.json_response({"error": "invalid_token"}, status=400)
    if status != 200:
        return web.json_response({"error": f"http_{status}"}, status=502)
    if not isinstance(data, dict):
        return web.json_response({"error": "network_error"}, status=502)
    if data.get("bot") is True:
        return web.json_response(
            {"error": "bot_token_not_supported"}, status=400
        )

    # A different session token of the MAIN account would open a second
    # gateway session and get both sessions killed.  The exact main token is
    # allowed: the bot routes it through its own session (MainVoiceBridge).
    main_token = load_root_bot_token()
    if not main_token or token != main_token:
        main_user_id = await _resolve_main_user_id(request, main_token)
        if main_user_id and str(data.get("id")) == main_user_id:
            return web.json_response(
                {"error": "main_account_session_token"}, status=400
            )

    existing = load_root_voice_tokens()
    if token in existing:
        return web.json_response({"error": "token_already_exists"}, status=409)

    if not add_root_voice_token(token):
        return web.json_response({"error": "config_write_failed"}, status=500)

    profile_store = request.app[TOKEN_PROFILE_STORE_KEY]
    if profile_store is not None:
        profile_store.remember(len(existing), data)

    service = request.app[VOICE_SERVICE_KEY]
    if service is not None:
        service.clear_cache()
    _queue_voice_reload(request)

    return web.json_response({"ok": True, "token": _voice_token_payload(data)})


async def delete_voice_token(request: web.Request) -> web.Response:
    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    if not _is_int(token_index) or token_index < 0:
        return _validation_error(["token_index must be a non-negative integer"])

    tokens = load_root_voice_tokens()
    if token_index >= len(tokens):
        return _validation_error(["token_index is out of range"])

    if not delete_root_voice_token(token_index):
        return web.json_response({"error": "config_write_failed"}, status=500)

    profile_store = request.app[TOKEN_PROFILE_STORE_KEY]
    if profile_store is not None:
        profile_store.forget(token_index)

    service = request.app[VOICE_SERVICE_KEY]
    if service is not None:
        service.clear_cache()
    _queue_voice_reload(request)

    return web.json_response({"ok": True})


def _queue_voice_reload(request: web.Request) -> None:
    """Ask the running bot to reload its voice token pool."""

    queue = request.app[VOICE_COMMAND_QUEUE_KEY]
    if queue is not None:
        queue.enqueue({"action": "reload"})


async def get_voice_soundboard(request: web.Request) -> web.Response:
    service = request.app[SOUNDBOARD_SERVICE_KEY]
    if service is None:
        return web.json_response({"error": "voice_unavailable"}, status=503)

    guild_id = (request.query.get("guild_id") or "").strip()
    token_index = _voice_token_index(request.query.get("token_index", "0"))
    errors = []
    if not _is_digits(guild_id):
        errors.append("guild_id must be a string of digits")
    if token_index is None:
        errors.append("token_index must be a non-negative integer")
    if errors:
        return _validation_error(errors)

    try:
        sounds = await service.list_server_sounds(token_index, guild_id)
    except VoiceError as error:
        return web.json_response({"error": error.message}, status=error.status)
    return web.json_response({"sounds": sounds})


async def get_voice_default_sounds(request: web.Request) -> web.Response:
    service = request.app[SOUNDBOARD_SERVICE_KEY]
    if service is None:
        return web.json_response({"error": "voice_unavailable"}, status=503)

    token_index = _voice_token_index(request.query.get("token_index", "0"))
    if token_index is None:
        return _validation_error(
            ["token_index must be a non-negative integer"]
        )

    try:
        sounds = await service.list_default_sounds(token_index)
    except VoiceError as error:
        return web.json_response({"error": error.message}, status=error.status)
    return web.json_response({"sounds": sounds})


async def post_voice_soundboard_play(request: web.Request) -> web.Response:
    service = request.app[SOUNDBOARD_SERVICE_KEY]
    if service is None:
        return web.json_response({"error": "voice_unavailable"}, status=503)

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    channel_id = body.get("channel_id")
    sound_id = body.get("sound_id")
    source_guild_id = body.get("source_guild_id")

    errors = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    if not _is_digits(channel_id):
        errors.append("channel_id must be a string of digits")
    if not _is_digits(sound_id):
        errors.append("sound_id must be a string of digits")
    if source_guild_id not in (None, "") and not _is_digits(source_guild_id):
        errors.append("source_guild_id must be a string of digits")
    if errors:
        return _validation_error(errors)

    try:
        result = await service.play(
            token_index,
            channel_id,
            sound_id,
            source_guild_id or None,
        )
    except VoiceError as error:
        return web.json_response({"error": error.message}, status=error.status)
    return web.json_response(result)


def _voice_queue_or_error(request):
    """Return the voice queue, or a 503 when it is missing or the bot is offline."""
    queue = request.app[VOICE_COMMAND_QUEUE_KEY]
    if queue is None:
        return None, web.json_response({"error": "voice_unavailable"}, status=503)
    checker = getattr(request.app[ADAPTER_KEY], "can_queue", None)
    if callable(checker):
        try:
            online = bool(checker())
        except Exception:
            logger.exception("Voice queue liveness check failed")
            online = False
        if not online:
            return None, web.json_response({"error": "bot_offline"}, status=503)
    return queue, None


async def post_voice_join(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    channels = body.get("channels")
    errors = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    if not isinstance(channels, list) or not 1 <= len(channels) <= 2:
        errors.append("channels must contain 1 or 2 channel IDs")
    elif not all(_is_digits(channel_id) for channel_id in channels):
        errors.append("channels must contain only numeric channel IDs")
    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {"action": "join", "token_index": token_index, "channels": channels}
    )
    return web.json_response({"queued": True})


async def post_voice_leave(request: web.Request) -> web.Response:
    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    channel_id = body.get("channel_id")
    errors = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    if not _is_digits(channel_id):
        errors.append("channel_id must be a string of digits")
    if errors:
        return _validation_error(errors)

    queue.enqueue(
        {
            "action": "leave",
            "token_index": token_index,
            "channel_id": channel_id,
        }
    )
    return web.json_response({"queued": True})


async def _post_voice_toggle(
    request: web.Request, action: str
) -> web.Response:
    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    token_index = body.get("token_index")
    enable = body.get("enable")
    errors = []
    if not _is_int(token_index) or token_index < 0:
        errors.append("token_index must be a non-negative integer")
    if not isinstance(enable, bool):
        errors.append("enable must be a boolean")
    if errors:
        return _validation_error(errors)

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error
    queue.enqueue(
        {
            "action": action,
            "token_index": token_index,
            "enable": enable,
        }
    )
    return web.json_response({"queued": True})


async def post_voice_stream(request: web.Request) -> web.Response:
    return await _post_voice_toggle(request, "stream")


async def post_voice_camera(request: web.Request) -> web.Response:
    return await _post_voice_toggle(request, "camera")


def _voice_token_index(value: Any) -> int | None:
    if isinstance(value, str) and len(value) > 10:
        return None
    try:
        token_index = int(value)
    except (TypeError, ValueError):
        return None
    return token_index if token_index >= 0 else None


def create_app(
    config: Optional[dict[str, Any]] = None,
    state_store: Optional[StateStore] = None,
    pairing_code: Optional[str] = None,
    adapter: Optional[BotAdapter] = None,
    allowed_hosts: Optional[set[str]] = None,
    profile_service: Optional[DiscordProfileService] = None,
    voice_service: Optional[VoiceTokenService] = None,
    token_profile_store: Optional[TokenProfileStore] = None,
    soundboard_service: Optional[SoundboardService] = None,
    voice_command_queue: Optional[VoiceCommandQueue] = None,
    voice_state_path: Optional[Path] = None,
    clone_queue: Optional[CloneCommandQueue] = None,
    clone_results: Optional[CloneResultStore] = None,
    emoji_queue: Optional[EmojiCommandQueue] = None,
    emoji_results: Optional[EmojiResultStore] = None,
) -> web.Application:
    """Build the dashboard application.

    ``pairing_code`` and ``state_store`` are injectable for tests.  Production
    callers normally pass a loaded config and a generated pairing code.
    """
    if config is None:
        resolved_config = load_config()
    else:
        resolved_config = copy.deepcopy(DEFAULT_CONFIG)
        resolved_config.update(config)

    app = web.Application(
        middlewares=[cors_middleware, security_middleware, auth_middleware]
    )
    app[CONFIG_KEY] = resolved_config
    app[STATE_STORE_KEY] = state_store or StateStore(
        Path(__file__).resolve().parent / "runtime_state.json"
    )
    app[ADAPTER_KEY] = adapter or OfflineBotAdapter()
    app[MAIN_ACCOUNT_ID_KEY] = {}
    app[PROFILE_SERVICE_KEY] = profile_service
    app[VOICE_SERVICE_KEY] = voice_service
    app[TOKEN_PROFILE_STORE_KEY] = token_profile_store
    app[TOKEN_PROFILE_WARMUP_KEY] = None
    if token_profile_store is not None:
        async def _warm_token_profiles(app: web.Application) -> None:
            app[TOKEN_PROFILE_WARMUP_KEY] = asyncio.create_task(
                token_profile_store.warm_up()
            )

        app.on_startup.append(_warm_token_profiles)
    app[SOUNDBOARD_SERVICE_KEY] = soundboard_service
    app[VOICE_COMMAND_QUEUE_KEY] = voice_command_queue
    app[VOICE_STATE_PATH_KEY] = (
        voice_state_path
        if voice_state_path is not None
        else Path(__file__).resolve().parent / "voice_state.json"
    )
    app[CLONE_QUEUE_KEY] = clone_queue
    app[CLONE_RESULTS_KEY] = clone_results
    app[EMOJI_QUEUE_KEY] = emoji_queue
    app[EMOJI_RESULTS_KEY] = emoji_results
    app[AUTH_KEY] = AuthManager(pairing_code or generate_pairing_code())
    host_source = (
        _default_allowed_hosts(resolved_config)
        if allowed_hosts is None
        else allowed_hosts
    )
    app[ALLOWED_HOSTS_KEY] = {host.lower() for host in host_source}

    origins = resolved_config.get("allowed_origins") or []
    if isinstance(origins, str):
        origins = [origins]
    app[ALLOWED_ORIGINS_KEY] = {
        origin for origin in origins if isinstance(origin, str) and origin
    }
    app[STARTED_AT_KEY] = time.monotonic()

    app.router.add_post("/api/v1/pair", pair)
    app.router.add_get("/api/v1/session", get_session)
    app.router.add_post("/api/v1/logout", logout)
    app.router.add_get("/api/v1/status", get_status)
    app.router.add_get("/api/v1/capabilities", get_capabilities)
    app.router.add_get("/api/v1/settings", get_settings)
    app.router.add_put("/api/v1/settings/prefix", put_settings_prefix)
    app.router.add_post("/api/v1/settings/reload", post_settings_reload)
    app.router.add_get("/api/v1/automation", get_automation)
    app.router.add_put("/api/v1/automation", put_automation)
    app.router.add_get("/api/v1/afk", get_afk)
    app.router.add_put("/api/v1/afk", put_afk)
    app.router.add_get("/api/v1/reactions", get_reactions)
    app.router.add_put("/api/v1/reactions", put_reactions)
    app.router.add_post("/api/v1/utility/weather", post_utility_weather)
    app.router.add_post("/api/v1/utility/image", post_utility_image)
    app.router.add_post("/api/v1/utility/emoji-copy", post_utility_emoji_copy)
    app.router.add_get(
        "/api/v1/utility/emoji-copy/status",
        get_utility_emoji_copy_status,
    )
    app.router.add_post("/api/v1/utility/clone", post_utility_clone)
    app.router.add_get(
        "/api/v1/utility/clone/status", get_utility_clone_status
    )
    app.router.add_get("/api/v1/voice/tokens", get_voice_tokens)
    app.router.add_post("/api/v1/voice/tokens", post_voice_token)
    app.router.add_delete("/api/v1/voice/tokens", delete_voice_token)
    app.router.add_get("/api/v1/voice/soundboard", get_voice_soundboard)
    app.router.add_get(
        "/api/v1/voice/soundboard/defaults", get_voice_default_sounds
    )
    app.router.add_post(
        "/api/v1/voice/soundboard/play", post_voice_soundboard_play
    )
    app.router.add_post("/api/v1/voice/join", post_voice_join)
    app.router.add_post("/api/v1/voice/leave", post_voice_leave)
    app.router.add_post("/api/v1/voice/stream", post_voice_stream)
    app.router.add_post("/api/v1/voice/camera", post_voice_camera)

    register_voice_api(app)
    app[VOICE_PROTECTED_PATHS_KEY] = voice_protected_paths()
    app[VOICE_PROTECTED_MUTATION_PATHS_KEY] = voice_protected_mutation_paths()

    return app
