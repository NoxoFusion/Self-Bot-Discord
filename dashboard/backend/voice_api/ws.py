"""WebSocket endpoint that pushes dashboard state in real time.

The REST API remains the source of truth and the fallback; this module only
adds a best-effort push channel.  A session cookie is required, exactly like
the protected REST routes, and no CSRF token is needed for a GET/WebSocket
upgrade.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from aiohttp import web

from ..config import load_root_voice_tokens
from ..voice import read_voice_state
from ..ws_hub import WsHub

logger = logging.getLogger(__name__)

PROTECTED_PATHS = {"/api/v1/ws"}

_APP_KEY_FACTORY = getattr(web, "AppKey", None)
WS_HUB_KEY = (
    _APP_KEY_FACTORY("ws_hub", WsHub)
    if _APP_KEY_FACTORY is not None
    else "ws_hub"
)
PUSH_INTERVAL_SECONDS = 2.0
BOT_HEARTBEAT_SECONDS = 10.0


def _token_count(voice: dict[str, Any]) -> int:
    """Prefer the configured pool size, falling back to the bot's state file."""

    try:
        configured = len(load_root_voice_tokens())
    except Exception:  # a malformed config must not kill the push loop
        configured = 0
    if configured:
        return configured

    tokens = voice.get("tokens")
    return len(tokens) if isinstance(tokens, list) else 0


def _slim_voice(voice: dict[str, Any] | None) -> dict[str, Any]:
    """Copy the state without the bulky per-token guild channel cache.

    The copy must never mutate the cached parsed state (T2 shares it).
    """

    if not isinstance(voice, dict):
        return {}
    slim = dict(voice)
    tokens = slim.get("tokens")
    if isinstance(tokens, list):
        slim["tokens"] = [
            (
                {k: v for k, v in token.items() if k != "guild_channels"}
                if isinstance(token, dict)
                else token
            )
            for token in tokens
        ]
    return slim


def _push_fingerprint(voice: dict[str, Any], bot: dict[str, Any]) -> tuple:
    """Identity of a push: voice changes plus non-volatile bot fields.

    ``latency_ms``/``uptime_seconds`` are excluded on purpose; the heartbeat
    refreshes them without spamming every tick.
    """

    return (
        voice.get("updated_at") if isinstance(voice, dict) else None,
        bot.get("state"),
        bot.get("username"),
        bot.get("user_id"),
        bot.get("guild_count"),
        bot.get("last_reload"),
    )


def _should_push(
    fingerprint: tuple,
    last_fingerprint: tuple | None,
    now: float,
    last_sent: float,
) -> bool:
    """Push when the state changed or the heartbeat is due."""

    if last_fingerprint is None:
        return True
    if fingerprint != last_fingerprint:
        return True
    return now - last_sent >= BOT_HEARTBEAT_SECONDS


def _state_payload(
    voice: dict[str, Any], bot: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "state",
        "bot": bot,
        "voice": _slim_voice(voice),
        "tokens": _token_count(voice),
    }


async def _broadcast_loop(app: web.Application) -> None:
    # Imported lazily to avoid an import cycle: app.py imports voice_api while
    # it is still defining create_app().
    from ..app import ADAPTER_KEY, VOICE_STATE_PATH_KEY

    hub: WsHub = app[WS_HUB_KEY]
    last_fingerprint: tuple | None = None
    last_sent = 0.0
    try:
        while True:
            await asyncio.sleep(PUSH_INTERVAL_SECONDS)
            try:
                if len(hub) == 0:
                    # No clients: skip the file/status reads entirely.
                    continue
                voice = read_voice_state(app[VOICE_STATE_PATH_KEY])
                bot = app[ADAPTER_KEY].get_status()
                now = time.monotonic()
                fingerprint = _push_fingerprint(voice, bot)
                if _should_push(
                    fingerprint, last_fingerprint, now, last_sent
                ):
                    await hub.broadcast(_state_payload(voice, bot))
                    last_fingerprint = fingerprint
                    last_sent = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("voice ws broadcast tick failed")
                continue
    except asyncio.CancelledError:
        raise


async def websocket_state(request: web.Request) -> web.WebSocketResponse:
    """Stream bot/voice state to one authenticated dashboard client."""

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    # Imported lazily to avoid an import cycle: app.py imports voice_api while
    # it is still defining create_app().
    from ..app import ADAPTER_KEY, VOICE_STATE_PATH_KEY

    hub: WsHub = request.app[WS_HUB_KEY]
    voice = read_voice_state(request.app[VOICE_STATE_PATH_KEY])
    bot = request.app[ADAPTER_KEY].get_status()
    try:
        # The first frame arrives immediately; the broadcaster sends the rest.
        await ws.send_str(json.dumps(_state_payload(voice, bot)))
    except Exception:
        return ws
    hub.add(ws)

    try:
        async for _message in ws:
            # The dashboard only consumes server pushes; client messages are
            # intentionally ignored.
            pass
    finally:
        hub.discard(ws)

    return ws


def register(app: web.Application) -> None:
    """Attach the WebSocket route, its hub and the broadcaster to ``app``."""

    if WS_HUB_KEY in app:
        return
    app[WS_HUB_KEY] = WsHub()
    app.router.add_get("/api/v1/ws", websocket_state)
    # The task lives in a closure, not an app key: mutating the application
    # after startup is deprecated in aiohttp.
    broadcaster: dict[str, asyncio.Task | None] = {"task": None}

    async def _start_broadcaster(current_app: web.Application) -> None:
        broadcaster["task"] = asyncio.create_task(
            _broadcast_loop(current_app)
        )

    async def _stop_broadcaster(current_app: web.Application) -> None:
        task = broadcaster["task"]
        broadcaster["task"] = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await current_app[WS_HUB_KEY].close_all()

    app.on_startup.append(_start_broadcaster)
    app.on_cleanup.append(_stop_broadcaster)
