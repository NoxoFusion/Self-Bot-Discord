"""Voice token liveness, soundboard, and command-queue helpers."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

from .discord_identity import discord_headers

DISCORD_API = "https://discord.com/api/v10"

TokenLoader = Callable[[], list[str]]
VoiceFetcher = Callable[
    [str, str, str, dict[str, Any] | None],
    Awaitable[tuple[int | None, Any]],
]


class VoiceError(Exception):
    """A voice operation failed with a user-readable reason."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _avatar_url(user_id: str, avatar_hash: str | None) -> str:
    if avatar_hash:
        extension = "gif" if avatar_hash.startswith("a_") else "png"
        return (
            f"https://cdn.discordapp.com/avatars/{user_id}/"
            f"{avatar_hash}.{extension}?size=128"
        )

    try:
        index = (int(user_id) >> 22) % 6
    except (TypeError, ValueError):
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


async def fetch_discord_json(
    token: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> tuple[int | None, Any]:
    """Call the Discord REST API with a user token (bot fallback on 401)."""

    token = token.strip() if isinstance(token, str) else ""
    if not token:
        return None, None

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            for authorization in (token, f"Bot {token}"):
                async with session.request(
                    method,
                    DISCORD_API + path,
                    headers={
                        "Authorization": authorization,
                        **discord_headers(token),
                    },
                    json=json_body,
                ) as response:
                    if response.status == 204:
                        return 204, None
                    try:
                        data = await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        data = None
                    if response.status == 401 and authorization == token:
                        continue
                    return response.status, data
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None, None

    return 401, None


class VoiceTokenService:
    """Read the configured voice tokens and report which are still alive."""

    def __init__(
        self,
        token_loader: TokenLoader,
        fetcher: VoiceFetcher = fetch_discord_json,
        ttl: float = 60.0,
        on_unauthorized: Callable[[list[int]], None] | None = None,
        state_reader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._token_loader = token_loader
        self._fetcher = fetcher
        self._ttl = ttl
        self._on_unauthorized = on_unauthorized
        self._state_reader = state_reader
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    def clear_cache(self) -> None:
        """Drop cached liveness results so the next read reloads the pool."""
        self._cached = None
        self._cached_at = 0.0

    def _tokens_from_state(self) -> dict[str, Any]:
        """Build the token list from the bot's voice state (no REST calls)."""

        tokens = self._token_loader()
        state = self._state_reader() if self._state_reader else {}
        entries = state.get("tokens") if isinstance(state, dict) else None
        by_index: dict[int, dict] = {}
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                index_value = entry.get("index")
                if isinstance(index_value, int) and not isinstance(
                    index_value, bool
                ):
                    by_index[index_value] = entry

        results: list[dict[str, Any]] = []
        for index, token in enumerate(tokens):
            if not isinstance(token, str) or not token.strip():
                continue
            entry = by_index.get(index) or {}
            user_id = str(entry.get("user_id") or "")
            username = entry.get("username")
            channels = entry.get("channels")
            results.append(
                {
                    "index": index,
                    # A configured token is valid until the bot evicts it;
                    # gateway_ready reports whether it is connected right now.
                    "alive": True,
                    "gateway_ready": bool(entry.get("gateway_ready")),
                    "username": username,
                    "display_name": username,
                    "user_id": user_id or None,
                    "avatar_url": (
                        _avatar_url(user_id, None) if user_id else None
                    ),
                    "channels": (
                        [str(channel) for channel in channels if channel]
                        if isinstance(channels, list)
                        else []
                    ),
                    "guild_id": entry.get("guild_id"),
                    "self_mute": bool(entry.get("self_mute", True)),
                    "self_deaf": bool(entry.get("self_deaf", False)),
                    "streaming": bool(entry.get("streaming")),
                    "video": bool(entry.get("video")),
                    "error": None,
                }
            )
        return {"tokens": results, "removed": 0}

    async def get_tokens(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached

        if self._state_reader is not None:
            payload = self._tokens_from_state()
            self._cached = payload
            self._cached_at = now
            return payload

        tokens = self._token_loader()
        results: list[dict[str, Any]] = []
        removed = 0
        unauthorized_indices: list[int] = []

        for index, token in enumerate(tokens):
            if not isinstance(token, str) or not token.strip():
                continue
            token = token.strip()
            status, data = await self._fetcher(token, "GET", "/users/@me")
            if status == 200 and isinstance(data, dict):
                user_id = str(data.get("id") or "")
                username = data.get("username")
                display_name = data.get("global_name") or username
                avatar_hash = data.get("avatar")
                results.append(
                    {
                        "index": index,
                        "alive": True,
                        "username": username,
                        "display_name": display_name,
                        "user_id": user_id,
                        "avatar_url": _avatar_url(
                            user_id,
                            avatar_hash if isinstance(avatar_hash, str) else None,
                        ),
                        "error": None,
                    }
                )
            elif status == 401:
                removed += 1
                unauthorized_indices.append(index)
            else:
                results.append(
                    {
                        "index": index,
                        "alive": False,
                        "username": None,
                        "display_name": None,
                        "user_id": None,
                        "avatar_url": None,
                        "error": "network_error" if status is None else f"http_{status}",
                    }
                )

        if unauthorized_indices and self._on_unauthorized is not None:
            try:
                self._on_unauthorized(unauthorized_indices)
                purged = True
            except Exception:
                purged = False
        else:
            purged = False

        payload = {"tokens": results, "removed": removed}
        if not purged:
            self._cached = payload
            self._cached_at = now
        return payload


class TokenProfileStore:
    """Fetch each token's public profile once and keep it for the process.

    The dashboard pool must not depend on raw-gateway liveness or re-fetch on
    every poll: names/avatars are fetched once at startup (configured tokens)
    or once when a token is added, then cached until the process exits.
    """

    def __init__(
        self,
        token_loader: TokenLoader,
        fetcher: VoiceFetcher = fetch_discord_json,
    ) -> None:
        self._token_loader = token_loader
        self._fetcher = fetcher
        self._profiles: dict[int, dict[str, Any]] = {}
        self._attempted: set[int] = set()

    @staticmethod
    def profile_from_user(data: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        user_id = str(data.get("id") or "")
        username = data.get("username")
        if not user_id or not isinstance(username, str) or not username:
            return None
        display_name = data.get("global_name") or username
        avatar_hash = data.get("avatar")
        return {
            "user_id": user_id,
            "username": username,
            "display_name": (
                display_name if isinstance(display_name, str) else username
            ),
            "avatar_url": _avatar_url(
                user_id,
                avatar_hash if isinstance(avatar_hash, str) else None,
            ),
        }

    def remember(self, index: int, data: dict[str, Any]) -> None:
        profile = self.profile_from_user(data)
        if profile is None:
            return
        self._profiles[int(index)] = profile
        self._attempted.add(int(index))

    def forget(self, index: int) -> None:
        """Drop a deleted token; later indices shift down (config delete pops)."""
        index = int(index)
        self._profiles.pop(index, None)
        self._attempted.discard(index)
        self._profiles = {
            (i - 1 if i > index else i): profile
            for i, profile in self._profiles.items()
        }
        self._attempted = {
            (i - 1 if i > index else i) for i in self._attempted
        }

    def profile_for(self, index: int) -> dict[str, Any] | None:
        return self._profiles.get(int(index))

    def apply(self, index: int, token: dict[str, Any]) -> None:
        """Overlay the cached profile onto a dashboard token payload."""
        profile = self._profiles.get(int(index))
        if not profile:
            return
        token["user_id"] = profile["user_id"]
        token["username"] = profile["username"]
        token["display_name"] = profile["display_name"]
        token["avatar_url"] = profile["avatar_url"]

    def _token_still_at(self, index: int, token: str) -> bool:
        """Whether ``token`` still occupies ``index`` (a delete shifts)."""
        try:
            tokens = self._token_loader()
        except Exception:
            return False
        if not isinstance(tokens, list) or not 0 <= index < len(tokens):
            return False
        entry = tokens[index]
        return isinstance(entry, str) and entry.strip() == token

    async def warm_up(self) -> None:
        """Fetch every configured token's profile exactly once."""
        tokens = self._token_loader()
        for index, token in enumerate(tokens):
            if not isinstance(token, str) or not token.strip():
                continue
            if index in self._attempted:
                continue
            self._attempted.add(index)
            cleaned = token.strip()
            try:
                status, data = await self._fetcher(
                    cleaned, "GET", "/users/@me"
                )
            except Exception:
                status, data = None, None
            if status == 200 and self._token_still_at(index, cleaned):
                self.remember(index, data)
            # Failures are intentionally not retried: one attempt per token
            # per process (restart the backend to retry).
            await asyncio.sleep(0.2)


class SoundboardService:
    """List and play Discord soundboard sounds using a voice token."""

    def __init__(
        self,
        token_loader: TokenLoader,
        fetcher: VoiceFetcher = fetch_discord_json,
    ) -> None:
        self._token_loader = token_loader
        self._fetcher = fetcher

    def _token(self, token_index: int) -> str:
        tokens = self._token_loader()
        if token_index < 0 or token_index >= len(tokens):
            raise VoiceError("token_not_configured", 400)
        token = tokens[token_index]
        if not isinstance(token, str) or not token.strip():
            raise VoiceError("token_not_configured", 400)
        return token.strip()

    async def list_server_sounds(
        self, token_index: int, guild_id: str
    ) -> list[dict[str, Any]]:
        token = self._token(token_index)
        status, data = await self._fetcher(
            token, "GET", f"/guilds/{guild_id}/soundboard-sounds"
        )
        if status != 200 or not isinstance(data, dict):
            raise VoiceError(
                "network_error" if status is None else f"http_{status}", 502
            )
        items = data.get("items")
        return items if isinstance(items, list) else []

    async def list_default_sounds(
        self, token_index: int
    ) -> list[dict[str, Any]]:
        token = self._token(token_index)
        status, data = await self._fetcher(
            token, "GET", "/soundboard-default-sounds"
        )
        if status != 200 or not isinstance(data, list):
            raise VoiceError(
                "network_error" if status is None else f"http_{status}", 502
            )
        return data

    async def play(
        self,
        token_index: int,
        channel_id: str,
        sound_id: str,
        source_guild_id: str | None = None,
    ) -> dict[str, Any]:
        token = self._token(token_index)
        payload: dict[str, Any] = {"sound_id": str(sound_id)}
        if source_guild_id:
            payload["source_guild_id"] = str(source_guild_id)

        status, data = await self._fetcher(
            token,
            "POST",
            f"/channels/{channel_id}/send-soundboard-sound",
            payload,
        )
        if status == 204:
            return {"ok": True}

        message = data.get("message") if isinstance(data, dict) else None
        raise VoiceError(
            message or ("network_error" if status is None else f"http_{status}"),
            502,
        )


class VoiceCommandQueue:
    """A tiny JSON-file queue consumed by the running self-bot process."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def enqueue(self, command: dict[str, Any]) -> None:
        directory = self.path.parent / f"{self.path.stem}.spool"
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns():020d}_{uuid.uuid4().hex}.json"
        temp = directory / f".{name}.tmp"
        temp.write_text(
            json.dumps(command, ensure_ascii=False), encoding="utf-8"
        )
        temp.replace(directory / name)


# Module-level cache: path -> ((mtime, size), parsed).  The backend is a
# single-threaded asyncio process, so no lock is needed.  Callers must treat
# the returned dict as read-only; the WS payload builder copies what it
# changes (see voice_api.ws._slim_voice).
_VOICE_STATE_CACHE: dict[str, tuple[tuple[float, int], dict[str, Any]]] = {}


def read_voice_state(path: Path) -> dict[str, Any]:
    """Read the state file written by the bot's Voice cog (mtime-cached).

    The returned dict is shared with the cache, so callers must treat it as
    read-only.  The WebSocket payload builder copies the parts it changes.
    """

    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (stat.st_mtime, stat.st_size)
    cache_key = str(path)
    cached = _VOICE_STATE_CACHE.get(cache_key)
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    parsed = data if isinstance(data, dict) else {}
    _VOICE_STATE_CACHE[cache_key] = (key, parsed)
    return parsed
