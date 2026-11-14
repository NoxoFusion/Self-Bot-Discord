"""Real Discord voice audio streaming for the dashboard voice tokens.

The signaling-only :mod:`src.voice_connector` connector cannot send media.  This
module owns one real ``discord.Client`` per secondary voice-token index and uses
the library's :class:`discord.VoiceClient` to connect to a voice channel and
play audio resolved by yt-dlp (or passed as a direct HTTP(S) URL).  The main
token is served by the bot's own client through ``client_provider`` so no
second gateway session is opened for it.

Public surface:

* ``audio_streamer`` — module-level :class:`AudioStreamer` singleton.
* ``AudioStreamer.play(index, guild_id, channel_id, query)``
* ``AudioStreamer.stop(index)`` / ``AudioStreamer.skip(index)``
* ``AudioStreamer.forcefix(index)`` — reconnect and restore playback
* ``AudioStreamer.state()`` / ``AudioStreamer.close_all()``

The dashboard action wrapper lives in :mod:`src.voice_actions.play`.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import discord

from src.audio_ffmpeg import ffmpeg_available, resolve_ffmpeg
from src.audio_filters import build_filter_chain, resolve_filter_name
from src.audio_search import (
    GLOBAL_SEARCH_CACHE,
    is_url,
    normalize_query,
    rank_entries,
)

try:  # Optional: only needed for search queries.
    import yt_dlp
except Exception:  # pragma: no cover - depends on the local installation
    yt_dlp = None  # type: ignore[assignment]

try:  # Optional: kept for backward compatibility.
    import imageio_ffmpeg
except Exception:  # pragma: no cover - depends on the local installation
    imageio_ffmpeg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

READY_TIMEOUT_SECONDS = 30.0
MAX_QUERY_LENGTH = 300

# Stall watchdog: check every 30s, consider playback stalled after 8s without
# progress and restart at most twice before dropping the track.
WATCHDOG_INTERVAL_SECONDS = 30.0
WATCHDOG_STALL_SECONDS = 8.0
WATCHDOG_MAX_RESTARTS = 2

# Pause between the forced disconnect and the reconnect in ``forcefix``.
FORCEFIX_RECONNECT_DELAY_SECONDS = 1.2

# Disconnect an audio client after this many seconds without playback.
# ``0`` disables the cleanup; override with ``audio.idle_cleanup_seconds``.
IDLE_CLEANUP_SECONDS = 30.0

# Re-resolve a looped track's stream URL when it was resolved longer ago
# than this.  YouTube throttles/expires resolved URLs after a while, so a
# loop that runs for hours would otherwise keep reusing a dead URL.
URL_REFRESH_SECONDS = 3600.0

# Discard a parked client (voice disconnected, queue kept) after this many
# seconds.  ``0`` keeps parked clients forever; override with
# ``audio.parked_cleanup_seconds``.
PARKED_CLEANUP_SECONDS = 600.0

_FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
_FFMPEG_OPTIONS = "-vn"

# Only these URL shapes are safe to hand to ffmpeg directly.  Everything else
# (YouTube/SoundCloud watch pages, etc.) must go through yt-dlp, otherwise
# ffmpeg tries to decode an HTML page and exits after a couple of seconds.
_DIRECT_MEDIA_SUFFIXES = {
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".flac",
    ".mp4",
    ".webm",
    ".m3u8",
    ".mpd",
    ".ts",
}


def _is_direct_media_url(query: str) -> bool:
    try:
        path = urlparse(query).path
    except Exception:
        return False
    return Path(path).suffix.lower() in _DIRECT_MEDIA_SUFFIXES


def _coerce_duration(value: Any) -> float | None:
    """Return a non-negative duration in seconds, or ``None``."""

    if value is None or isinstance(value, bool):
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration < 0:
        return None
    return duration


def _cache_get(key: str) -> Any:
    """Read the shared search cache from the synchronous resolve worker."""

    getter = getattr(GLOBAL_SEARCH_CACHE, "get_sync", None)
    if not callable(getter):
        return None
    try:
        return getter(key)
    except Exception:
        logger.debug("Voice audio search cache get failed", exc_info=True)
        return None


def _cache_put(key: str, value: Any) -> None:
    """Write the shared search cache from the synchronous resolve worker."""

    putter = getattr(GLOBAL_SEARCH_CACHE, "put_sync", None)
    if not callable(putter):
        return
    try:
        putter(key, value)
    except Exception:
        logger.debug("Voice audio search cache put failed", exc_info=True)


def _load_voice_tokens() -> list[str]:
    """Read the ``voice_token`` pool from the repository-root config.

    Empty entries are preserved so indexes keep matching the dashboard/bot
    configuration.  A missing or malformed config yields an empty list.
    """

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    tokens = raw.get("voice_token") if isinstance(raw, dict) else None
    if not isinstance(tokens, list):
        return []
    return [token.strip() if isinstance(token, str) else "" for token in tokens]


def _load_idle_cleanup_seconds() -> float:
    """Read ``audio.idle_cleanup_seconds`` from the repository-root config.

    Missing or malformed values fall back to :data:`IDLE_CLEANUP_SECONDS`.
    Negative values are clamped to ``0`` (disabled).
    """

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return IDLE_CLEANUP_SECONDS

    audio = raw.get("audio") if isinstance(raw, dict) else None
    value = audio.get("idle_cleanup_seconds") if isinstance(audio, dict) else None
    if value is None or isinstance(value, bool):
        return IDLE_CLEANUP_SECONDS
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return IDLE_CLEANUP_SECONDS
    return max(0.0, seconds)


def _load_parked_cleanup_seconds() -> float:
    """Read ``audio.parked_cleanup_seconds`` from the repository-root config.

    Missing or malformed values fall back to :data:`PARKED_CLEANUP_SECONDS`.
    Negative values are clamped to ``0`` (keep parked clients forever).
    """

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return PARKED_CLEANUP_SECONDS

    audio = raw.get("audio") if isinstance(raw, dict) else None
    value = audio.get("parked_cleanup_seconds") if isinstance(audio, dict) else None
    if value is None or isinstance(value, bool):
        return PARKED_CLEANUP_SECONDS
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return PARKED_CLEANUP_SECONDS
    return max(0.0, seconds)


class _CountingSource(discord.AudioSource):
    """AudioSource wrapper that counts decoded bytes for the stall watchdog.

    A wall-clock position always advances, so it cannot tell a stalled
    ffmpeg from a healthy one.  The byte count only moves when ffmpeg
    actually produces audio.
    """

    def __init__(self, inner: discord.AudioSource) -> None:
        self._inner = inner
        self.bytes_read = 0

    def read(self):
        data = self._inner.read()
        if data:
            self.bytes_read += len(data)
        return data

    def is_opus(self) -> bool:
        return self._inner.is_opus()

    def cleanup(self) -> None:
        cleanup = getattr(self._inner, "cleanup", None)
        if callable(cleanup):
            cleanup()


class _AudioClient(discord.Client):
    """One real gateway/voice client for a single voice-token index."""

    def __init__(self, token_index: int, token: str):
        super().__init__()
        self.token_index = int(token_index)
        self.token = token
        self.queue: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.loop_mode: str = "off"
        self.started_at: float | None = None
        self.active_filters: set[str] = set()
        self.bass_level: int = 10
        self.volume_pct: int = 100
        self.ready = asyncio.Event()
        self.lock = asyncio.Lock()
        self.guild_id: str | None = None
        self.channel_id: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._watchdog_track: dict[str, Any] | None = None
        self._watchdog_last_position: float | None = None
        self._watchdog_last_seen: float | None = None
        self._watchdog_restarts: int = 0
        self._playing_source: Any = None
        self._idle_since: float | None = None
        self.self_flags: dict[str, bool] = {}
        self._parked = False
        self._parked_since: float | None = None

    async def on_ready(self) -> None:  # noqa: D401 - discord.py event name
        """Mark the client ready once the gateway handshake completes."""

        logger.info(
            "Voice audio client %s is ready", AudioStreamer._client_label(self)
        )
        self.ready.set()

    def start_background(self) -> asyncio.Task:
        """Start the Discord client without blocking the caller."""

        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(
            self.start(self.token),
            name=f"voice-audio-{self.token_index}",
        )
        return self._task

    async def wait_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> None:
        """Wait for ``on_ready`` or fail with an actionable error."""

        if self.ready.is_set():
            return
        if self._task is None:
            raise RuntimeError(
                f"Voice audio client #{self.token_index} was not started"
            )

        ready_waiter = asyncio.create_task(self.ready.wait())
        try:
            done, _pending = await asyncio.wait(
                {ready_waiter, self._task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if not ready_waiter.done():
                ready_waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ready_waiter

        if self.ready.is_set():
            return

        if self._task in done:
            if self._task.cancelled():
                raise RuntimeError(
                    f"Voice audio client #{self.token_index} was cancelled before ready"
                )
            exc = self._task.exception()
            if exc is not None:
                raise RuntimeError(
                    f"Voice audio client #{self.token_index} failed to start: {exc}"
                ) from exc
            raise RuntimeError(
                f"Voice audio client #{self.token_index} stopped before becoming ready"
            )

        raise RuntimeError(
            f"Voice audio client #{self.token_index} was not ready after "
            f"{timeout:.0f}s (check the token and network)"
        )

    async def close(self) -> None:
        """Stop the gateway task and release the HTTP/voice resources."""

        self._closed = True
        self.ready.clear()

        task = self._task
        self._task = None
        if (
            task is not None
            and not task.done()
            and task is not asyncio.current_task()
        ):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        try:
            await super().close()
        except Exception:
            logger.debug(
                "Voice audio client %s close failed",
                AudioStreamer._client_label(self),
                exc_info=True,
            )


class _MainClientAdapter:
    """Expose the main bot through the client surface used by playback.

    The main bot owns the only gateway session for its token, so this adapter
    never starts, closes or replaces it.  It only keeps the per-index queue and
    delegates guild/voice lookups to the bot.
    """

    def __init__(self, bot: Any, index: int):
        self.bot = bot
        self.token_index = int(index)
        self.queue: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.loop_mode: str = "off"
        self.started_at: float | None = None
        self.active_filters: set[str] = set()
        self.bass_level: int = 10
        self.volume_pct: int = 100
        self.lock = asyncio.Lock()
        self.guild_id: str | None = None
        self.channel_id: str | None = None
        self.last_error: str | None = None
        self._watchdog_track: dict[str, Any] | None = None
        self._watchdog_last_position: float | None = None
        self._watchdog_last_seen: float | None = None
        self._watchdog_restarts: int = 0
        self._playing_source: Any = None
        self.self_flags: dict[str, bool] = {}
        self._parked = False
        self._parked_since: float | None = None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self.ready = asyncio.Event()
        if self._bot_ready():
            self.ready.set()

    def _bot_ready(self) -> bool:
        checker = getattr(self.bot, "is_ready", None)
        if checker is None:
            # No readiness API on this object; assume the supplied client is
            # usable rather than blocking playback for the full timeout.
            return True
        try:
            return bool(checker()) if callable(checker) else bool(checker)
        except Exception:
            return False

    async def wait_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not (self.ready.is_set() or self._bot_ready()):
            if loop.time() >= deadline:
                raise RuntimeError(
                    f"Main voice client #{self.token_index} is not ready after "
                    f"{timeout:.0f}s"
                )
            await asyncio.sleep(0.25)
        self.ready.set()

    @property
    def voice_clients(self) -> list[Any]:
        try:
            return list(getattr(self.bot, "voice_clients", None) or [])
        except Exception:
            return []

    @property
    def voice_client(self) -> Any | None:
        voices = self.voice_clients
        return voices[0] if voices else None

    def get_guild(self, guild_id: int) -> Any | None:
        getter = getattr(self.bot, "get_guild", None)
        if not callable(getter):
            return None
        return getter(guild_id)

    async def close(self) -> None:
        """Never close the main bot — the adapter owns no gateway session."""


class AudioStreamer:
    """Manage per-token Discord clients, queues and playback."""

    WATCHDOG_INTERVAL_SECONDS = WATCHDOG_INTERVAL_SECONDS
    WATCHDOG_STALL_SECONDS = WATCHDOG_STALL_SECONDS
    WATCHDOG_MAX_RESTARTS = WATCHDOG_MAX_RESTARTS

    def __init__(
        self,
        token_loader: Callable[[], list[str]] | None = None,
        client_provider: Callable[[int], Any | None] | None = None,
        watchdog_enabled: bool = True,
    ):
        self._clients: dict[int, Any] = {}
        self._creation_locks: dict[int, asyncio.Lock] = {}
        # Volume/filter changes made before a client exists are kept here and
        # applied when the client is created on the first play.
        self._pending_defaults: dict[int, dict] = {}
        self._token_loader = token_loader or _load_voice_tokens
        self._client_provider = client_provider
        self._watchdog_enabled = bool(watchdog_enabled)
        self._watchdog_task: asyncio.Task | None = None
        self._idle_cleanup_seconds = _load_idle_cleanup_seconds()
        self._parked_cleanup_seconds = _load_parked_cleanup_seconds()

    def _creation_lock(self, index: int) -> asyncio.Lock:
        lock = self._creation_locks.get(index)
        if lock is None:
            lock = asyncio.Lock()
            self._creation_locks[index] = lock
        return lock

    def set_client_provider(
        self, provider: Callable[[int], Any | None] | None
    ) -> None:
        """Set the callable returning an existing client for an index."""

        self._client_provider = provider

    def _provided_client(self, index: int) -> Any | None:
        provider = self._client_provider
        if not callable(provider):
            return None
        try:
            return provider(index)
        except Exception:
            logger.exception(
                "Voice audio client provider failed for #%s", index
            )
            return None

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------
    def _token_for(self, index: int) -> str:
        try:
            tokens = self._token_loader()
        except Exception as exc:
            raise RuntimeError(f"Could not load voice tokens: {exc}") from exc

        if not isinstance(tokens, list) or not 0 <= index < len(tokens):
            raise RuntimeError(f"Voice token #{index} is not configured")
        token = tokens[index]
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError(f"Voice token #{index} is empty")
        return token.strip()

    def _create_client(self, index: int, token: str) -> _AudioClient:
        return _AudioClient(index, token)

    @staticmethod
    async def _close_client(client: Any) -> None:
        close = getattr(client, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _discard_client(self, index: int) -> None:
        client = self._clients.get(index)
        if client is None:
            return
        label = self._client_label(client)
        self._clients.pop(index, None)
        try:
            await self._close_client(client)
        except Exception:
            logger.debug("Voice audio client %s discard failed", label, exc_info=True)

    async def _cleanup_session(self, index: int) -> None:
        """Stop playback, disconnect and close the client for ``index``.

        Used by Stop and by the idle cleanup.  Never raises so a broken client
        cannot interrupt the watchdog loop or a close sequence.
        """

        client = self._clients.get(index)
        if client is None:
            return
        label = self._client_label(client)

        try:
            async with client.lock:
                voice = self._voice_for(client)
                if voice is not None:
                    with contextlib.suppress(Exception):
                        voice.stop()
                    with contextlib.suppress(Exception):
                        await voice.disconnect(force=True)
                client.current = None
                client.queue.clear()
                client._idle_since = None
                self._retire_source(client)
                client._parked = False
                client._parked_since = None
        except Exception:
            logger.debug(
                "Voice audio %s cleanup failed", label, exc_info=True
            )

        try:
            await self._discard_client(index)
        except Exception:
            logger.debug(
                "Voice audio %s cleanup discard failed", label, exc_info=True
            )

        # The dashboard reads voice_state.json; a watchdog-driven cleanup does
        # not pass through the cog command loop, so refresh the snapshot here.
        try:
            from cogs.voice import _write_voice_state
        except Exception:
            return
        try:
            _write_voice_state()
        except Exception:
            logger.debug(
                "Voice audio %s state write after cleanup failed",
                label,
                exc_info=True,
            )

    def _apply_pending_defaults(self, index: int, client: Any) -> None:
        """Apply and clear volume/filter changes made before client creation."""

        pending = self._pending_defaults.pop(index, None)
        if not pending:
            return
        volume_pct = pending.get("volume_pct")
        if volume_pct is not None:
            client.volume_pct = volume_pct
        filters = pending.get("filters")
        if filters is not None:
            client.active_filters = set(filters)
        bass_level = pending.get("bass_level")
        if bass_level is not None:
            client.bass_level = bass_level

    async def _get_client(self, index: int) -> Any:
        provided = self._provided_client(index)
        client = self._clients.get(index)

        if provided is not None:
            # Reuse the main bot instead of opening a second gateway session.
            created = False
            if not isinstance(client, _MainClientAdapter) or client.bot is not provided:
                if client is not None:
                    await self._discard_client(index)
                client = _MainClientAdapter(provided, index)
                self._clients[index] = client
                created = True
            try:
                await client.wait_ready(READY_TIMEOUT_SECONDS)
            except Exception:
                logger.warning(
                    "Main voice client %s is not ready",
                    self._client_label(client),
                    exc_info=True,
                )
                await self._discard_client(index)
                raise
            if created:
                self._apply_pending_defaults(index, client)
            return client

        if isinstance(client, _MainClientAdapter):
            # The provider no longer supplies the main bot for this index.
            await self._discard_client(index)
            client = None

        if client is not None and not getattr(client, "_closed", False):
            try:
                wait_ready = getattr(client, "wait_ready", None)
                if callable(wait_ready):
                    await wait_ready(READY_TIMEOUT_SECONDS)
                return client
            except Exception:
                logger.warning(
                    "Voice audio client %s is not ready; recreating it",
                    self._client_label(client),
                    exc_info=True,
                )
                await self._discard_client(index)

        token = self._token_for(index)
        client = self._create_client(index, token)
        self._clients[index] = client
        try:
            start = getattr(client, "start_background", None)
            if callable(start):
                start()
            wait_ready = getattr(client, "wait_ready", None)
            if callable(wait_ready):
                await wait_ready(READY_TIMEOUT_SECONDS)
        except Exception as exc:
            self._clients.pop(index, None)
            with contextlib.suppress(Exception):
                await self._close_client(client)
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(
                f"Voice audio client {self._client_label(client)} could not start: {exc}"
            ) from exc
        self._apply_pending_defaults(index, client)
        # The raw signaling connector is a second gateway session for the
        # same token.  Audio now owns the session, so stop the raw one and
        # give Discord a moment to clear its voice state.
        self._stop_raw_gateway(index)
        await asyncio.sleep(0.3)
        return client

    # ------------------------------------------------------------------
    # Media resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _stream_options() -> dict[str, Any]:
        """Options for resolving a concrete video/page into a stream."""

        return {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "no_warnings": True,
        }

    @classmethod
    def _legacy_options(cls) -> dict[str, Any]:
        """Options for the single-step ``ytsearch1`` fallback."""

        options = cls._stream_options()
        options["default_search"] = "ytsearch1"
        return options

    @staticmethod
    def _extract_info(query: str, options: dict[str, Any]) -> dict[str, Any]:
        """Run one yt-dlp extraction and return its info dictionary."""

        ydl = None
        try:
            ydl = yt_dlp.YoutubeDL(options)
            info = ydl.extract_info(query, download=False)
        except Exception as exc:
            logger.warning("Voice audio could not resolve %r: %s", query, exc)
            raise RuntimeError(
                f"yt-dlp could not resolve {query!r}: {exc}"
            ) from exc
        finally:
            close = getattr(ydl, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()

        if not isinstance(info, dict):
            raise RuntimeError(f"yt-dlp returned no media for {query!r}")
        return info

    def _extract_stream(
        self, query: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract a playable stream URL, title and duration."""

        info = self._extract_info(query, options)

        entries = info.get("entries")
        if (
            isinstance(entries, Sequence)
            and not isinstance(entries, (str, bytes))
            and entries
        ):
            entry = next(
                (item for item in entries if isinstance(item, dict)),
                None,
            )
            if entry is None:
                raise RuntimeError(f"yt-dlp returned no media for {query!r}")
            info = entry

        url = info.get("url")
        if not isinstance(url, str) or not url:
            raise RuntimeError(f"yt-dlp returned no stream URL for {query!r}")

        title = info.get("title")
        if not isinstance(title, str) or not title.strip():
            title = query
        title = title.strip()
        duration = _coerce_duration(info.get("duration"))
        logger.info("Voice audio resolved %r -> %r", query, title)
        return {"url": url, "title": title, "duration": duration}

    def _flat_search(
        self, query: str, normalized: str, modifiers: set[str]
    ) -> str | None:
        """Search flat results, rank them and return the best video URL."""

        options = {
            "extract_flat": True,
            "quiet": True,
            "noplaylist": True,
            "no_warnings": True,
            "nocheckcertificate": True,
        }
        try:
            info = self._extract_info(f"ytsearch10:{query}", options)
        except RuntimeError:
            return None

        entries = info.get("entries")
        if not isinstance(entries, Sequence) or isinstance(
            entries, (str, bytes)
        ):
            return None
        candidates = [entry for entry in entries if isinstance(entry, dict)]
        if not candidates:
            return None

        for entry in rank_entries(candidates, normalized, modifiers):
            webpage_url = entry.get("webpage_url")
            if isinstance(webpage_url, str) and webpage_url.startswith(
                ("http://", "https://")
            ):
                return webpage_url
            video_id = entry.get("id")
            if isinstance(video_id, str) and video_id.strip():
                return f"https://www.youtube.com/watch?v={video_id.strip()}"
        return None

    def _resolve(self, query: str) -> dict[str, Any]:
        """Resolve a direct URL or search query to a playable stream URL."""

        query = query.strip()
        if query.startswith(("http://", "https://")) and _is_direct_media_url(
            query
        ):
            return {"url": query, "title": query}

        if yt_dlp is None:
            raise RuntimeError(
                "yt-dlp is not installed; install yt-dlp to play search queries"
            )

        if is_url(query):
            return self._extract_stream(query, self._stream_options())

        normalized, modifiers = normalize_query(query)
        cache_key = f"{normalized}:{':'.join(sorted(modifiers))}"
        cached = _cache_get(cache_key)
        if (
            isinstance(cached, dict)
            and isinstance(cached.get("url"), str)
            and cached["url"]
        ):
            logger.info("Voice audio cache hit for %r", query)
            return dict(cached)

        webpage_url = self._flat_search(query, normalized, modifiers)
        if webpage_url is not None:
            result = self._extract_stream(
                webpage_url, self._stream_options()
            )
        else:
            logger.info(
                "Voice audio flat search found nothing for %r; "
                "falling back to ytsearch1",
                query,
            )
            result = self._extract_stream(query, self._legacy_options())

        _cache_put(cache_key, result)
        return result

    def _build_source(
        self,
        url: str,
        *,
        options: str | None = None,
        start_seconds: float = 0,
        loop: bool = False,
    ) -> discord.AudioSource:
        """Create the ffmpeg audio source for ``url``.

        ``options`` is appended to the base ``-vn`` options so callers can add
        filters (for example ``-af volume=0.5``) without changing the
        reconnect behavior.  A positive ``start_seconds`` prepends an input
        seek (``-ss``) while keeping the reconnect flags intact.  ``loop``
        makes ffmpeg repeat the input itself (``-stream_loop -1``) so a looped
        track has no re-open gap and no repeated URL fetch.
        """

        executable = resolve_ffmpeg()
        ffmpeg_options = _FFMPEG_OPTIONS
        if options:
            ffmpeg_options = f"{_FFMPEG_OPTIONS} {options}"

        before_options = _FFMPEG_BEFORE_OPTIONS
        if loop:
            before_options = f"-stream_loop -1 {before_options}"
        try:
            start = float(start_seconds)
        except (TypeError, ValueError):
            start = 0.0
        if start > 0:
            before_options = f"-ss {start:g} {before_options}"

        try:
            return discord.FFmpegPCMAudio(
                url,
                executable=executable,
                before_options=before_options,
                options=ffmpeg_options,
            )
        except Exception as exc:
            raise RuntimeError(f"Could not start ffmpeg: {exc}") from exc

    # ------------------------------------------------------------------
    # Voice helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _voices(client: Any) -> list[Any]:
        voices = getattr(client, "voice_clients", None)
        if voices is None:
            single = getattr(client, "voice_client", None)
            return [single] if single is not None else []
        return list(voices or [])

    @classmethod
    def _voice_for(cls, client: Any) -> Any | None:
        for voice in cls._voices(client):
            try:
                if voice is not None and voice.is_connected():
                    return voice
            except Exception:
                continue
        return None

    async def _connect_voice(self, client: Any, channel: Any) -> Any:
        voice = self._voice_for(client)
        if voice is not None:
            current = getattr(voice, "channel", None)
            if current is None or int(getattr(current, "id", 0)) != int(channel.id):
                await voice.move_to(channel)
            return voice

        # A disconnected/stale voice protocol can still be registered on the
        # client and make ``channel.connect`` raise "Already connected".
        stale = next(iter(self._voices(client)), None)
        if stale is not None:
            with contextlib.suppress(Exception):
                await stale.disconnect(force=True)

        return await channel.connect(
            cls=discord.VoiceClient,
            self_deaf=False,
            self_mute=False,
        )

    async def _resolve_guild_from_channel(
        self, client: Any, channel_number: int, channel_id: str, index: int
    ) -> int:
        """Derive the guild id for ``channel_number`` from the voice client.

        The dashboard may not know the guild when the raw gateway is stopped,
        so the channel itself is the source of truth.  Prefer the gateway
        lookup and fall back to the raw REST channel endpoint.
        """

        try:
            fetcher = getattr(client, "fetch_channel", None)
            if not callable(fetcher):
                fetcher = getattr(
                    getattr(client, "bot", None), "fetch_channel", None
                )
            if callable(fetcher):
                fetched = await fetcher(channel_number)
                guild = getattr(fetched, "guild", None)
                guild_number = getattr(guild, "id", None)
                if guild_number is not None:
                    return int(guild_number)

            http = getattr(client, "http", None)
            getter = getattr(http, "get_channel", None)
            if not callable(getter):
                http = getattr(getattr(client, "bot", None), "http", None)
                getter = getattr(http, "get_channel", None)
            if not callable(getter):
                raise RuntimeError(
                    "the client does not expose channel lookups"
                )
            data = await getter(channel_number)
            return int(data["guild_id"])
        except Exception as exc:
            raise RuntimeError(
                f"Could not find channel {channel_id} for voice token "
                f"{self._client_label(client)}: {exc}"
            ) from exc

    @staticmethod
    async def _fetch_guild(client: Any, guild_number: int) -> Any | None:
        """Fetch a guild the client has not cached yet, or return ``None``."""

        fetcher = getattr(client, "fetch_guild", None)
        if not callable(fetcher):
            fetcher = getattr(
                getattr(client, "bot", None), "fetch_guild", None
            )
        if not callable(fetcher):
            return None
        try:
            return await fetcher(guild_number)
        except Exception:
            logger.debug(
                "Voice audio could not fetch guild %s",
                guild_number,
                exc_info=True,
            )
            return None

    async def _release_raw_voice(self, index: int, guild_id: str) -> None:
        """Hand voice ownership to the audio client.

        The raw signaling connector and this audio client are two gateway
        sessions of the same account.  Leaving the guild through the raw
        session first prevents both sessions from fighting over the
        account-level voice state during the media handshake.
        """

        client = self._clients.get(index)
        label = self._client_label(client) if client is not None else f"#{index}"
        try:
            from cogs.voice import voice_manager
        except Exception:
            return
        try:
            connections = voice_manager.get_all_voice(index) or {}
            in_guild = any(
                str(getattr(connection, "guild_id", "")) == str(guild_id)
                and getattr(connection, "voice_connected", False)
                for connection in connections.values()
            )
            if not in_guild:
                return
            voice_manager.leave_channel(index, str(guild_id))
            await asyncio.sleep(0.4)
        except Exception:
            logger.debug(
                "Voice audio %s could not release the raw voice state",
                label,
                exc_info=True,
            )

    def _stop_raw_gateway(self, index: int) -> None:
        """Stop every raw signaling session for ``index`` (gateway + legacy).

        The raw connector and this audio client are gateway sessions of the
        same account.  Multi-mode joins keep one extra session per guild in
        ``voice_connectors``; leaving any of them alive breaks the
        single-owner rule and hides voice state from the dashboard.
        """

        client = self._clients.get(index)
        label = self._client_label(client) if client is not None else f"#{index}"
        try:
            from cogs.voice import voice_manager
        except Exception:
            return

        stopped = 0

        try:
            connector = voice_manager.gateway_connectors.pop(index, None)
        except Exception:
            connector = None
            logger.debug(
                "Voice audio %s could not remove the raw gateway",
                label,
                exc_info=True,
            )
        if connector is not None:
            try:
                connector.stop()
                stopped += 1
            except Exception:
                logger.debug(
                    "Voice audio %s could not stop the raw gateway",
                    label,
                    exc_info=True,
                )

        # Legacy per-guild sessions (multi-mode) — same account, extra
        # gateways.  Key shape is f"{index}_{guild_id}" so the prefix
        # f"{index}_" cannot collide (index 1 never matches "10_...").
        try:
            keys = [
                key
                for key in list(voice_manager.voice_connectors)
                if str(key).startswith(f"{index}_")
            ]
        except Exception:
            keys = []
        for key in keys:
            connector = voice_manager.voice_connectors.pop(key, None)
            if connector is None:
                continue
            try:
                connector.stop()
                stopped += 1
            except Exception:
                logger.debug(
                    "Voice audio %s could not stop raw session %s",
                    label,
                    key,
                    exc_info=True,
                )

        if stopped:
            logger.debug(
                "Voice audio %s stopped %s raw session(s)", label, stopped
            )

    # ------------------------------------------------------------------
    # Voice ownership (self state, moves, parked clients)
    # ------------------------------------------------------------------
    def has_client(self, index: int) -> bool:
        """Return whether a client is registered for ``index``."""

        return index in self._clients

    def owns_voice(self, index: int) -> bool:
        """Return whether ``index`` currently owns a connected voice client."""

        client = self._clients.get(index)
        return client is not None and self._voice_for(client) is not None

    async def _send_ws(self, client: Any, payload: dict) -> bool:
        """Send a raw gateway payload through the client's websocket."""

        ws = getattr(client, "ws", None) or getattr(
            getattr(client, "bot", None), "ws", None
        )
        sender = getattr(ws, "send_as_json", None)
        if not callable(sender):
            return False
        try:
            result = sender(payload)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            logger.debug(
                "Voice audio %s ws send failed",
                self._client_label(client),
                exc_info=True,
            )
            return False

    async def send_presence(self, index: int, payload: dict) -> bool:
        """Send a presence payload through the audio client that owns ``index``."""

        client = self._clients.get(index)
        if client is None:
            return False
        ws = getattr(client, "ws", None) or getattr(
            getattr(client, "bot", None), "ws", None
        )
        sender = getattr(ws, "send_as_json", None)
        if not callable(sender):
            return False
        try:
            result = sender(payload)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            logger.debug(
                "Voice audio %s presence send failed",
                self._client_label(client),
                exc_info=True,
            )
            return False

    async def set_self_state(
        self,
        index: int,
        self_mute: bool | None = None,
        self_deaf: bool | None = None,
        self_stream: bool | None = None,
        self_video: bool | None = None,
    ) -> bool:
        """Update mute/deaf/video/stream flags for the connected voice.

        The current channel is always preserved: an op4 with a ``None``
        channel would leave the voice channel instead of updating flags.
        """

        client = self._clients.get(index)
        if client is None:
            return False
        voice = self._voice_for(client)
        if voice is None:
            return False

        guild = getattr(voice, "guild", None)
        if guild is None and getattr(client, "guild_id", None):
            try:
                guild = client.get_guild(int(client.guild_id))
            except (TypeError, ValueError):
                guild = None
        guild_id = getattr(guild, "id", None) or getattr(
            client, "guild_id", None
        )
        if guild_id is None:
            return False

        channel = getattr(voice, "channel", None)
        channel_id = getattr(channel, "id", None) or getattr(
            client, "channel_id", None
        )
        if channel_id is None:
            return False

        flags = getattr(client, "self_flags", None) or {}
        live = self._live_self_flags(voice)
        current_mute = self._pick_flag(live, flags, "self_mute")
        current_deaf = self._pick_flag(live, flags, "self_deaf")
        current_video = self._pick_flag(live, flags, "self_video")
        current_stream = self._pick_flag(live, flags, "self_stream")

        mute = bool(self_mute) if self_mute is not None else bool(current_mute)
        deaf = bool(self_deaf) if self_deaf is not None else bool(current_deaf)
        video = bool(self_video) if self_video is not None else current_video
        stream = bool(self_stream) if self_stream is not None else current_stream

        if self_mute is not None or self_deaf is not None or self_video is not None:
            payload = {
                "op": 4,
                "d": {
                    "guild_id": str(guild_id),
                    "channel_id": str(channel_id),
                    "self_mute": mute,
                    "self_deaf": deaf,
                    "self_video": video,
                },
            }
            if not await self._send_ws(client, payload):
                return False

        if self_stream is not None:
            user = getattr(client, "user", None) or getattr(
                getattr(client, "bot", None), "user", None
            )
            user_id = getattr(user, "id", None)
            if user_id is None:
                return False
            key = f"guild:{guild_id}:{channel_id}:{user_id}"
            if stream:
                start_payload = {
                    "op": 18,
                    "d": {
                        "type": "guild",
                        "guild_id": str(guild_id),
                        "channel_id": str(channel_id),
                        "preferred_region": None,
                    },
                }
                if not await self._send_ws(client, start_payload):
                    return False
                if not await self._send_ws(
                    client,
                    {"op": 22, "d": {"stream_key": key, "paused": False}},
                ):
                    return False
            else:
                if not await self._send_ws(
                    client, {"op": 19, "d": {"stream_key": key}}
                ):
                    return False

        client.self_flags = {
            "self_mute": mute,
            "self_deaf": deaf,
            "self_stream": stream,
            "self_video": video,
        }
        return True

    async def move_to(self, index: int, channel_id: str) -> bool:
        """Move a client's voice connection to ``channel_id``."""

        client = self._clients.get(index)
        if client is None:
            return False
        try:
            channel_number = int(channel_id)
        except (TypeError, ValueError):
            return False

        guild = None
        raw_guild_id = getattr(client, "guild_id", None)
        if raw_guild_id:
            try:
                guild = client.get_guild(int(raw_guild_id))
            except (TypeError, ValueError):
                guild = None
        if guild is not None and guild.get_channel(channel_number) is None:
            # The target channel belongs to another guild; resolve it from
            # the channel instead of failing on the cached guild.
            guild = None
        if guild is None:
            try:
                guild_number = await self._resolve_guild_from_channel(
                    client, channel_number, str(channel_id), index
                )
            except Exception:
                logger.debug(
                    "Voice audio %s could not resolve guild for channel %s",
                    self._client_label(client),
                    channel_id,
                    exc_info=True,
                )
                return False
            guild = client.get_guild(guild_number) or await self._fetch_guild(
                client, guild_number
            )
        if guild is None:
            return False
        channel = guild.get_channel(channel_number)
        if channel is None:
            return False

        voice = self._voice_for(client)
        if voice is None or not voice.is_connected():
            await self._connect_voice(client, channel)
            # A fresh connection starts unmuted (see _connect_voice).
            client.self_flags = {
                "self_mute": False,
                "self_deaf": False,
                "self_stream": False,
                "self_video": False,
            }
        else:
            current = getattr(voice, "channel", None)
            if current is None or int(getattr(current, "id", 0)) != channel_number:
                await voice.move_to(channel)
                # Go Live/camera end when the voice channel changes.
                flags = getattr(client, "self_flags", None)
                if isinstance(flags, dict):
                    flags["self_stream"] = False
                    flags["self_video"] = False

        client.guild_id = str(guild.id)
        client.channel_id = str(channel.id)

        if getattr(client, "_parked", False):
            client._parked = False
            client._parked_since = None
            client._idle_since = None
            async with client.lock:
                if client.current is None:
                    # Empty queue: _start_next_locked arms the idle
                    # cleanup so the client does not outlive its use.
                    self._start_next_locked(client)
        return True

    async def disconnect_voice(self, index: int) -> bool:
        """Park a client: disconnect voice but keep its client and queue."""

        client = self._clients.get(index)
        if client is None:
            return False
        if getattr(client, "_parked", False):
            return True

        async with client.lock:
            voice = self._voice_for(client)
            if voice is None:
                return False
            current = getattr(client, "current", None)
            if isinstance(current, dict):
                client.queue.insert(0, self._without_seek(current))
                client.current = None
            with contextlib.suppress(Exception):
                voice.stop()
            with contextlib.suppress(Exception):
                await voice.disconnect(force=True)
            client._parked = True
            client._parked_since = time.monotonic()
            client._idle_since = None
            self._retire_source(client)
            # Go Live/camera end when the voice connection drops.
            flags = getattr(client, "self_flags", None)
            if isinstance(flags, dict):
                flags["self_stream"] = False
                flags["self_video"] = False
        return True

    @staticmethod
    def _live_self_flags(voice: Any) -> dict[str, bool | None]:
        """Read the live self flags from the gateway voice-state cache.

        ``VoiceClient._connection.self_voice_state`` is the member's real
        ``VoiceState`` (updated by every VOICE_STATE_UPDATE), so it reflects
        changes made from any Discord client — not just this dashboard.
        """

        connection = getattr(voice, "_connection", None)
        live = getattr(connection, "self_voice_state", None)
        return {
            "self_mute": getattr(live, "self_mute", None),
            "self_deaf": getattr(live, "self_deaf", None),
            "self_stream": getattr(live, "self_stream", None),
            "self_video": getattr(live, "self_video", None),
        }

    @staticmethod
    def _pick_flag(
        live: dict, tracked: dict, key: str, default: bool = False
    ) -> bool:
        value = live.get(key)
        if isinstance(value, bool):
            return value
        tracked_value = tracked.get(key)
        return bool(tracked_value) if isinstance(tracked_value, bool) else default

    @staticmethod
    def _client_name(client: Any) -> str | None:
        """Return the public account name for a client, when known."""
        user = getattr(client, "user", None) or getattr(
            getattr(client, "bot", None), "user", None
        )
        name = getattr(user, "name", None)
        return name if isinstance(name, str) and name.strip() else None

    @classmethod
    def _client_label(cls, client: Any) -> str:
        """Human label for logs: ``#0 (alice)`` or ``#0`` when unknown."""
        index = getattr(client, "token_index", "?")
        name = cls._client_name(client)
        return f"#{index} ({name})" if name else f"#{index}"

    def client_name(self, index: int) -> str | None:
        """Public account name for ``index``, or ``None``."""
        client = self._clients.get(index)
        return self._client_name(client) if client is not None else None

    def voice_flags(self, index: int) -> dict | None:
        """Return the voice ownership snapshot for ``index``."""

        client = self._clients.get(index)
        if client is None:
            return None

        voice = self._voice_for(client)
        flags = getattr(client, "self_flags", None) or {}
        live = self._live_self_flags(voice) if voice is not None else {}
        guild_id = getattr(client, "guild_id", None)
        channel_id = getattr(client, "channel_id", None)
        if voice is not None:
            channel = getattr(voice, "channel", None)
            if channel is not None:
                channel_id = getattr(channel, "id", channel_id)
            guild = getattr(voice, "guild", None)
            if guild is not None:
                guild_id = getattr(guild, "id", guild_id)

        current = getattr(client, "current", None)
        queue = getattr(client, "queue", None) or []
        return {
            "connected": voice is not None,
            "parked": bool(getattr(client, "_parked", False)),
            "guild_id": str(guild_id) if guild_id else None,
            "channel_id": str(channel_id) if channel_id else None,
            "self_mute": self._pick_flag(live, flags, "self_mute"),
            "self_deaf": self._pick_flag(live, flags, "self_deaf"),
            "self_stream": self._pick_flag(live, flags, "self_stream"),
            "self_video": self._pick_flag(live, flags, "self_video"),
            "audio_active": bool(current) or bool(queue),
            "audio_playing": bool(current),
        }

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    @staticmethod
    def _mark_idle(client: Any) -> None:
        """Arm the idle-cleanup timer when playback has nothing left to do."""

        if getattr(client, "_parked", False):
            return
        if getattr(client, "_idle_since", None) is None:
            client._idle_since = time.monotonic()

    def _start_next_locked(self, client: Any) -> None:
        """Start the next queued track.  Caller must hold ``client.lock``."""

        if getattr(client, "current", None) is not None:
            return
        queue = getattr(client, "queue", None)
        if not queue:
            self._mark_idle(client)
            return

        voice = self._voice_for(client)
        if voice is None or not voice.is_connected():
            self._mark_idle(client)
            return

        item = queue.pop(0)
        client.current = item
        chain = build_filter_chain(
            getattr(client, "active_filters", None) or set(),
            getattr(client, "bass_level", 10),
            getattr(client, "volume_pct", 100),
        )
        start_seconds = _coerce_duration(item.get("start_seconds"))
        loop_track = getattr(client, "loop_mode", "off") == "track"
        build_kwargs: dict[str, Any] = {}
        if chain:
            build_kwargs["options"] = f"-af {chain}"
        if start_seconds is not None:
            build_kwargs["start_seconds"] = start_seconds
        if loop_track:
            build_kwargs["loop"] = True
        try:
            source = self._build_source(item["url"], **build_kwargs)
        except Exception as exc:
            client.current = None
            client.last_error = str(exc)
            logger.exception(
                "Voice audio %s: could not build source for %r",
                self._client_label(client),
                item.get("title"),
            )
            if queue:
                self._start_next_locked(client)
            else:
                self._mark_idle(client)
            return

        try:
            playable = _CountingSource(source)
            voice.play(
                playable,
                after=lambda error, c=client, it=item: self._schedule_after(
                    c, error, it
                ),
            )
            client._playing_source = playable
            client.started_at = time.monotonic()
            client.last_error = None
            client._idle_since = None
            logger.info(
                "Voice audio %s playing %r",
                self._client_label(client),
                item.get("title"),
            )
        except Exception as exc:
            client._playing_source = None
            client.current = None
            client.last_error = str(exc)
            with contextlib.suppress(Exception):
                source.cleanup()
            logger.exception(
                "Voice audio %s: could not start %r",
                self._client_label(client),
                item.get("title"),
            )
            if queue:
                self._start_next_locked(client)
            else:
                self._mark_idle(client)

    @staticmethod
    def _without_seek(item: dict) -> dict:
        """Return a copy of ``item`` that starts from the beginning."""

        copy = dict(item)
        copy.pop("start_seconds", None)
        return copy

    @staticmethod
    def _position_at(client: Any, now: float) -> float:
        """Return the track position at monotonic time ``now``."""

        current = getattr(client, "current", None)
        if not isinstance(current, dict):
            return 0.0
        position = _coerce_duration(current.get("start_seconds")) or 0.0
        started_at = getattr(client, "started_at", None)
        if isinstance(started_at, (int, float)) and not isinstance(
            started_at, bool
        ):
            position += max(0.0, now - started_at)
        return max(0.0, position)

    @staticmethod
    def _normalize_position(client: Any, position: float) -> float:
        """Wrap a looping track's position back into its duration."""
        current = getattr(client, "current", None)
        if not isinstance(current, dict):
            return position
        duration = _coerce_duration(current.get("duration"))
        if duration and duration > 0:
            return position % duration
        return position

    @classmethod
    def _current_position_seconds(cls, client: Any) -> float:
        """Return the current track position, including a previous seek."""

        return cls._normalize_position(
            client, cls._position_at(client, time.monotonic())
        )

    def _watchdog_position(self, client: Any, now: float) -> float:
        """Return the playback progress used by the watchdog (test seam).

        Real progress is the number of decoded bytes: unlike a wall-clock
        estimate it stops moving when the source is actually stalled.
        """

        source = getattr(client, "_playing_source", None)
        bytes_read = getattr(source, "bytes_read", None)
        if isinstance(bytes_read, (int, float)) and not isinstance(
            bytes_read, bool
        ):
            return float(bytes_read)
        return self._position_at(client, now)

    async def _refresh_track_url_locked(self, client: Any, track: dict) -> None:
        """Re-resolve a stalled track's URL from its original query.

        YouTube throttles/expires resolved URLs; reusing the cached URL
        makes every watchdog restart fail again.  A fresh resolve gives the
        restart a working URL.  Caller must hold ``client.lock``.
        """
        if not isinstance(track, dict):
            return
        query = track.get("query")
        if not isinstance(query, str) or not query.strip():
            return
        try:
            fresh = await asyncio.to_thread(self._resolve, query)
        except Exception:
            logger.debug(
                "Voice audio %s: could not refresh the source URL",
                self._client_label(client),
                exc_info=True,
            )
            return
        if not isinstance(fresh, dict):
            return
        url = fresh.get("url")
        if not isinstance(url, str) or not url:
            return
        track["url"] = url
        track["resolved_at"] = time.monotonic()
        duration = _coerce_duration(fresh.get("duration"))
        if duration is not None:
            track["duration"] = duration

    def _restart_current_locked(
        self, client: Any, position: float | None = None
    ) -> None:
        """Restart the current track at its current position.

        The caller must hold ``client.lock``.  The snapshot is copied so the
        stale ``after`` callback from ``voice.stop()`` cannot be mistaken for
        the restarted item.
        """

        current = getattr(client, "current", None)
        if not isinstance(current, dict):
            return

        item = dict(current)
        if position is None:
            position = self._current_position_seconds(client)
        position = self._normalize_position(client, position)

        voice = self._voice_for(client)
        if voice is not None:
            with contextlib.suppress(Exception):
                voice.stop()

        self._retire_source(client)
        client.current = None
        item["start_seconds"] = position
        client.queue.insert(0, item)
        self._start_next_locked(client)

    def _schedule_after(self, client: Any, error: Exception | None, item: dict) -> None:
        """Bridge the audio thread callback back onto the asyncio loop."""

        loop = getattr(client, "_loop", None)
        if not isinstance(loop, asyncio.AbstractEventLoop) or loop.is_closed():
            loop = getattr(client, "loop", None)
        if not isinstance(loop, asyncio.AbstractEventLoop) or loop.is_closed():
            logger.warning(
                "Voice audio %s: no running loop for the after callback",
                self._client_label(client),
            )
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._handle_after(client, error, item),
                loop,
            )
        except Exception:
            logger.exception(
                "Voice audio %s: could not schedule the next track",
                self._client_label(client),
            )

    async def _handle_after(
        self, client: Any, error: Exception | None, item: dict
    ) -> None:
        title = item.get("title") if isinstance(item, dict) else None
        if error is not None:
            logger.warning(
                "Voice audio %s playback error for %r: %s",
                self._client_label(client),
                title,
                error,
            )
        else:
            logger.info(
                "Voice audio %s finished %r",
                self._client_label(client),
                title,
            )
        async with client.lock:
            if getattr(client, "current", None) is not item:
                # A stop/skip already moved on; ignore the stale callback.
                return
            loop_mode = getattr(client, "loop_mode", "off")
            if loop_mode in {"track", "queue"}:
                requeued = self._without_seek(item)
                resolved_at = requeued.get("resolved_at")
                if (
                    isinstance(resolved_at, (int, float))
                    and not isinstance(resolved_at, bool)
                    and time.monotonic() - resolved_at > URL_REFRESH_SECONDS
                ):
                    await self._refresh_track_url_locked(client, requeued)
                if loop_mode == "track":
                    client.queue.insert(0, requeued)
                else:
                    client.queue.append(requeued)
            self._clear_playing_source(client)
            client.current = None
            try:
                self._start_next_locked(client)
            except Exception:
                logger.exception(
                    "Voice audio %s: could not advance the queue",
                    self._client_label(client),
                )
            if (
                not getattr(client, "_parked", False)
                and getattr(client, "current", None) is None
                and not getattr(client, "queue", None)
            ):
                client._idle_since = time.monotonic()

    # ------------------------------------------------------------------
    # Stall watchdog
    # ------------------------------------------------------------------
    @staticmethod
    def _clear_playing_source(client: Any) -> None:
        """Drop the finished source reference so ffmpeg is not kept alive."""
        try:
            client._playing_source = None
        except Exception:
            pass

    @staticmethod
    def _retire_source(client: Any) -> None:
        """Kill a possibly hung ffmpeg and drop the source reference.

        ``VoiceClient.stop`` only drops its player reference; a source whose
        ffmpeg process is blocked in ``read`` keeps the player thread (and the
        process) alive.  Cleaning it up closes the pipe so the orphan thread
        exits, and its stale ``after`` callback is ignored by the
        ``current is not item`` guard.
        """
        source = getattr(client, "_playing_source", None)
        if source is not None:
            with contextlib.suppress(Exception):
                source.cleanup()
        try:
            client._playing_source = None
        except Exception:
            pass

    @staticmethod
    def _reset_watchdog_state(client: Any) -> None:
        client._watchdog_track = None
        client._watchdog_last_position = None
        client._watchdog_last_seen = None
        client._watchdog_restarts = 0

    @staticmethod
    def _set_watchdog_state(
        client: Any,
        track: Any,
        position: float,
        now: float,
        restarts: int,
    ) -> None:
        client._watchdog_track = track
        client._watchdog_last_position = position
        client._watchdog_last_seen = now
        client._watchdog_restarts = restarts

    async def _watchdog_restart(
        self, client: Any, track: dict, position: float
    ) -> bool:
        """Restart ``track`` at ``position`` if it is still current."""

        async with client.lock:
            if getattr(client, "current", None) is not track:
                return False
            await self._refresh_track_url_locked(client, track)
            self._restart_current_locked(client, position)
            return True

    async def _watchdog_drop(self, client: Any, track: dict) -> bool:
        """Drop a track that keeps stalling and advance the queue."""

        async with client.lock:
            if getattr(client, "current", None) is not track:
                return False
            voice = self._voice_for(client)
            if voice is not None:
                with contextlib.suppress(Exception):
                    voice.stop()
            self._retire_source(client)
            client.current = None
            try:
                self._start_next_locked(client)
            except Exception:
                logger.debug(
                    "Voice audio %s: watchdog could not advance the queue",
                    self._client_label(client),
                    exc_info=True,
                )
            return True

    async def _watchdog_check_client(self, client: Any, now: float) -> None:
        """Check one client for a stalled track at monotonic time ``now``."""

        current = getattr(client, "current", None)
        if not isinstance(current, dict):
            self._reset_watchdog_state(client)
            return

        voice = self._voice_for(client)
        if voice is None:
            return

        is_paused = getattr(voice, "is_paused", None)
        if callable(is_paused):
            try:
                if is_paused():
                    return
            except Exception:
                logger.debug(
                    "Voice audio %s: watchdog pause check failed",
                    self._client_label(client),
                    exc_info=True,
                )

        is_playing = True
        playing = getattr(voice, "is_playing", None)
        if callable(playing):
            try:
                is_playing = bool(playing())
            except Exception:
                is_playing = True

        progress = max(0.0, self._watchdog_position(client, now))
        track = current
        last_track = getattr(client, "_watchdog_track", None)
        last_position = getattr(client, "_watchdog_last_position", None)
        last_seen = getattr(client, "_watchdog_last_seen", None)

        if (
            last_track is not track
            or last_position is None
            or last_seen is None
        ):
            self._set_watchdog_state(client, track, progress, now, 0)
            return

        advanced = progress > last_position + 0.05
        if advanced and is_playing:
            self._set_watchdog_state(client, track, progress, now, 0)
            return
        if advanced:
            # Keep the last healthy timestamp: a voice that is not playing is
            # stalled even though the byte progress kept moving.
            client._watchdog_last_position = progress
        if now - last_seen < WATCHDOG_STALL_SECONDS:
            return

        restarts = int(getattr(client, "_watchdog_restarts", 0) or 0) + 1
        if restarts > WATCHDOG_MAX_RESTARTS:
            dropped = await self._watchdog_drop(client, track)
            self._reset_watchdog_state(client)
            if dropped:
                logger.warning(
                    "Voice audio %s dropped a stalled track after %s restarts",
                    self._client_label(client),
                    WATCHDOG_MAX_RESTARTS,
                )
            return

        restarted = await self._watchdog_restart(
            client, track, self._current_position_seconds(client)
        )
        if not restarted:
            self._reset_watchdog_state(client)
            return
        self._set_watchdog_state(
            client,
            getattr(client, "current", None),
            self._watchdog_position(client, now),
            now,
            restarts,
        )
        logger.info(
            "Voice audio %s restarted a stalled track (attempt %s/%s)",
            self._client_label(client),
            restarts,
            WATCHDOG_MAX_RESTARTS,
        )

    async def _watchdog_check(self, now: float | None = None) -> None:
        """Check every client once; never let one failure stop the loop."""

        if now is None:
            now = time.monotonic()
        for client in list(self._clients.values()):
            try:
                await self._watchdog_check_client(client, now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Voice audio watchdog check failed for %s",
                    self._client_label(client),
                    exc_info=True,
                )

    async def _idle_cleanup_check(self, now: float | None = None) -> None:
        """Disconnect clients that stayed idle longer than the configured limit."""

        if now is None:
            now = time.monotonic()

        for index, client in list(self._clients.items()):
            try:
                if getattr(client, "_parked", False):
                    parked_limit = self._parked_cleanup_seconds
                    if parked_limit <= 0:
                        continue
                    parked_since = getattr(client, "_parked_since", None)
                    if not isinstance(parked_since, (int, float)) or isinstance(
                        parked_since, bool
                    ):
                        continue
                    if now - parked_since < parked_limit:
                        continue
                    await self._cleanup_session(index)
                    continue

                limit = self._idle_cleanup_seconds
                if limit <= 0:
                    continue
                idle_since = getattr(client, "_idle_since", None)
                if not isinstance(idle_since, (int, float)) or isinstance(
                    idle_since, bool
                ):
                    continue
                if getattr(client, "current", None) is not None:
                    continue
                if getattr(client, "queue", None):
                    continue
                if now - idle_since < limit:
                    continue
                await self._cleanup_session(index)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Voice audio %s idle cleanup check failed",
                    self._client_label(client),
                    exc_info=True,
                )

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                try:
                    await self._watchdog_check()
                    await self._idle_cleanup_check()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug(
                        "Voice audio watchdog iteration failed", exc_info=True
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Voice audio watchdog stopped", exc_info=True)

    def _ensure_watchdog(self) -> None:
        """Start the watchdog once, lazily, on the running loop."""

        if not self._watchdog_enabled:
            return
        task = self._watchdog_task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._watchdog_task = loop.create_task(
            self._watchdog_loop(), name="voice-audio-watchdog"
        )

    async def _stop_watchdog(self) -> None:
        task = self._watchdog_task
        self._watchdog_task = None
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def play(
        self,
        index: int,
        guild_id: str,
        channel_id: str,
        query: str,
    ) -> dict[str, Any]:
        """Join/connect and enqueue ``query`` for ``index``.

        ``guild_id`` may be empty; the guild is then derived from
        ``channel_id`` after the voice client is ready.

        Returns ``{"queued": True, "title": ..., "position": ...}``.  Raises
        ``RuntimeError`` with a human-readable message on configuration,
        connection or media-resolution failures.
        """

        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise RuntimeError(f"Invalid voice token index: {index!r}")
        if not isinstance(query, str) or not query.strip():
            raise RuntimeError("A non-empty query is required")
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise RuntimeError(
                f"Query must be {MAX_QUERY_LENGTH} characters or fewer"
            )

        has_guild = guild_id not in (None, "")
        try:
            channel_number = int(channel_id)
            guild_number = int(guild_id) if has_guild else None
        except (TypeError, ValueError) as exc:
            raise RuntimeError("guild_id and channel_id must be numeric") from exc

        async with self._creation_lock(index):
            client = await self._get_client(index)

        if guild_number is None:
            guild_number = await self._resolve_guild_from_channel(
                client, channel_number, channel_id, index
            )
            guild = client.get_guild(guild_number)
            if guild is None:
                guild = await self._fetch_guild(client, guild_number)
            if guild is None:
                raise RuntimeError(
                    f"Guild {guild_number} is not available to voice token "
                    f"{self._client_label(client)}"
                )
        else:
            guild = client.get_guild(guild_number)
            if guild is None:
                raise RuntimeError(
                    f"Guild {guild_id} is not available to voice token "
                    f"{self._client_label(client)}"
                )
        guild_label = guild_id if has_guild else guild_number
        channel = guild.get_channel(channel_number)
        if channel is None:
            raise RuntimeError(
                f"Channel {channel_id} was not found in guild {guild_label}"
            )

        try:
            item = await asyncio.to_thread(self._resolve, query)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Could not resolve {query!r}: {exc}") from exc

        if (
            not isinstance(item, dict)
            or not isinstance(item.get("url"), str)
            or not item["url"]
        ):
            raise RuntimeError(f"Could not resolve a playable URL for {query!r}")

        title = item.get("title") or query
        duration = _coerce_duration(item.get("duration"))
        item = {
            "url": item["url"],
            "title": title,
            "query": query,
            "resolved_at": time.monotonic(),
        }
        if duration is not None:
            item["duration"] = duration

        async with client.lock:
            voice = self._voice_for(client)
            if voice is None or not voice.is_connected():
                # Only hand off when the audio client is not already the
                # voice owner; otherwise the raw leave would kick playback.
                await self._release_raw_voice(
                    index, str(getattr(guild, "id", guild_id))
                )
            try:
                voice = await self._connect_voice(client, channel)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not connect voice token {self._client_label(client)} "
                    f"to channel {channel_id}: {exc}"
                ) from exc

            client.guild_id = str(getattr(guild, "id", guild_id))
            client.channel_id = str(getattr(channel, "id", channel_id))
            client._parked = False
            client._parked_since = None

            client.queue.append(item)
            client._idle_since = None
            position = len(client.queue)
            if client.current is None and not voice.is_playing():
                client.last_error = None
                self._start_next_locked(client)
                if client.current is None:
                    raise RuntimeError(
                        getattr(client, "last_error", None)
                        or f"Voice playback did not start for {title!r}"
                    )

        result: dict[str, Any] = {
            "queued": True,
            "title": title,
            "position": position,
        }
        if item.get("duration") is not None:
            result["duration"] = item["duration"]
        self._ensure_watchdog()
        return result

    async def skip(self, index: int) -> None:
        """Stop the current track and advance to the next queued one."""

        client = self._clients.get(index)
        if client is None:
            return

        async with client.lock:
            voice = self._voice_for(client)
            if (
                voice is not None
                and (client.current is not None or voice.is_playing())
            ):
                with contextlib.suppress(Exception):
                    voice.stop()
            self._retire_source(client)
            if client.current is not None:
                client.current = None
            # Advance explicitly.  A real VoiceClient also fires its ``after``
            # callback, but that callback carries the old item and is ignored
            # by ``_handle_after`` because ``current`` has already moved on.
            self._start_next_locked(client)

    async def set_loop(self, index: int, mode: str) -> str:
        """Set the loop mode (``off``, ``track`` or ``queue``) for ``index``."""

        if mode not in {"off", "track", "queue"}:
            raise RuntimeError(f"Invalid loop mode: {mode!r}")

        client = self._clients.get(index)
        if client is None:
            raise RuntimeError(f"Voice audio #{index} is not active")

        async with client.lock:
            previous = getattr(client, "loop_mode", "off")
            client.loop_mode = mode
            if previous != mode and getattr(client, "current", None) is not None:
                # Rebuild the ffmpeg source so the ``-stream_loop`` flag is
                # applied/removed at the current position.
                self._restart_current_locked(client)
        return mode

    async def apply_filters(
        self,
        index: int,
        active: list[str],
        bass_level: int | None = None,
    ) -> dict[str, Any]:
        """Set the active filter presets and restart the current track.

        Unknown filter names are ignored.  ``bass_level`` is clamped to
        1..999; when omitted the client's existing level is kept.  When no
        client exists yet the values are stored as pending defaults and
        applied on the first play instead of raising.
        """

        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise RuntimeError(f"Invalid voice token index: {index!r}")

        if isinstance(active, str) or not isinstance(
            active, (list, tuple, set, frozenset)
        ):
            raise RuntimeError("filters must be a list of strings")

        resolved: set[str] = set()
        for raw in active:
            if not isinstance(raw, str):
                continue
            name = resolve_filter_name(raw)
            if name is not None:
                resolved.add(name)

        client = self._clients.get(index)

        if bass_level is None:
            if client is not None:
                current_bass = getattr(client, "bass_level", 10)
            else:
                current_bass = self._pending_defaults.get(index, {}).get(
                    "bass_level", 10
                )
            if isinstance(current_bass, bool) or not isinstance(
                current_bass, int
            ):
                current_bass = 10
            new_bass = max(1, min(999, current_bass))
        else:
            if isinstance(bass_level, bool) or not isinstance(bass_level, int):
                raise RuntimeError(f"Invalid bass level: {bass_level!r}")
            new_bass = max(1, min(999, bass_level))

        if client is None:
            pending = self._pending_defaults.setdefault(index, {})
            pending["filters"] = sorted(resolved)
            pending["bass_level"] = new_bass
            return {"filters": sorted(resolved), "bass_level": new_bass}

        async with client.lock:
            client.active_filters = resolved
            client.bass_level = new_bass
            self._restart_current_locked(client)

        return {"filters": sorted(resolved), "bass_level": new_bass}

    async def set_volume(self, index: int, volume_pct: int) -> int:
        """Set playback volume (0..200%) and restart the current track.

        When no client exists yet the value is stored as a pending default and
        applied on the first play instead of raising.
        """

        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise RuntimeError(f"Invalid voice token index: {index!r}")

        if (
            isinstance(volume_pct, bool)
            or not isinstance(volume_pct, int)
            or not 0 <= volume_pct <= 200
        ):
            raise RuntimeError(f"Invalid volume: {volume_pct!r}")

        client = self._clients.get(index)
        if client is None:
            pending = self._pending_defaults.setdefault(index, {})
            pending["volume_pct"] = volume_pct
            return volume_pct

        async with client.lock:
            client.volume_pct = volume_pct
            self._restart_current_locked(client)

        return volume_pct

    async def replay(self, index: int) -> bool:
        """Restart the current track from the beginning.

        Returns ``True`` when a track was restarted, ``False`` when idle.
        """

        client = self._clients.get(index)
        if client is None:
            return False

        async with client.lock:
            current = getattr(client, "current", None)
            if not isinstance(current, dict):
                return False

            # Use a copy: ``voice.stop`` fires the ``after`` callback for the
            # original item, and the restarted track must not be mistaken for
            # that stale callback when it runs after this method yields.
            # Replay always starts from the beginning, so drop any seek offset
            # left by a filter/volume restart.
            item = self._without_seek(current)

            voice = self._voice_for(client)
            if voice is not None:
                with contextlib.suppress(Exception):
                    voice.stop()

            self._retire_source(client)
            client.current = None
            client.queue.insert(0, item)
            self._start_next_locked(client)

        return True

    async def forcefix(self, index: int) -> dict[str, Any]:
        """Force a full voice reconnect and restore the current playback.

        The queue, loop mode, filters, bass level and volume are snapshotted
        before the voice client is disconnected, then restored after the
        reconnect.  The current track resumes at its previous position.
        """

        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise RuntimeError(f"Invalid voice token index: {index!r}")

        client = self._clients.get(index)
        if client is None:
            raise RuntimeError(f"Voice token #{index} is not active")

        voice = self._voice_for(client)
        if voice is None:
            # A parked client (Leave kept the queue) reconnects and
            # resumes instead of erroring out.
            if getattr(client, "_parked", False) and getattr(
                client, "channel_id", None
            ):
                ok = await self.move_to(index, client.channel_id)
                if ok:
                    return {
                        "restored": False,
                        "title": None,
                        "position_ms": 0,
                        "queue": len(getattr(client, "queue", []) or []),
                    }
            raise RuntimeError(
                f"Voice token {self._client_label(client)} is not connected"
            )

        async with client.lock:
            current = getattr(client, "current", None)
            current_snapshot = (
                dict(current) if isinstance(current, dict) else None
            )
            position = (
                max(0.0, self._current_position_seconds(client))
                if current_snapshot is not None
                else 0.0
            )
            queue_snapshot = [
                dict(item)
                for item in (getattr(client, "queue", None) or [])
                if isinstance(item, dict)
            ]
            loop_mode = getattr(client, "loop_mode", "off")
            raw_filters = getattr(client, "active_filters", None)
            if isinstance(raw_filters, str) or not isinstance(
                raw_filters, (set, frozenset, list, tuple)
            ):
                active_filters: set[str] = set()
            else:
                active_filters = {
                    name for name in raw_filters if isinstance(name, str)
                }
            bass_level = getattr(client, "bass_level", 10)
            volume_pct = getattr(client, "volume_pct", 100)
            guild_id = getattr(client, "guild_id", None)
            channel_id = getattr(client, "channel_id", None)

            if guild_id is None or channel_id is None:
                raise RuntimeError(
                    f"Voice token {self._client_label(client)} has no active "
                    f"guild or channel"
                )

            with contextlib.suppress(Exception):
                await voice.disconnect(force=True)
            self._retire_source(client)
            client.current = None
            await asyncio.sleep(FORCEFIX_RECONNECT_DELAY_SECONDS)

            try:
                guild_number = int(guild_id)
                channel_number = int(channel_id)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Voice token {self._client_label(client)} has an invalid "
                    f"guild or channel"
                ) from exc

            guild = client.get_guild(guild_number)
            if guild is None:
                raise RuntimeError(
                    f"Guild {guild_id} is not available to voice token "
                    f"{self._client_label(client)}"
                )
            channel = guild.get_channel(channel_number)
            if channel is None:
                raise RuntimeError(
                    f"Channel {channel_id} was not found in guild {guild_id}"
                )

            try:
                await self._connect_voice(client, channel)
            except Exception as exc:
                raise RuntimeError(
                    f"Voice token {self._client_label(client)} could not "
                    f"reconnect to channel {channel_id}: {exc}"
                ) from exc

            client.loop_mode = loop_mode
            client.active_filters = active_filters
            client.bass_level = bass_level
            client.volume_pct = volume_pct
            client.guild_id = str(guild_id)
            client.channel_id = str(channel_id)
            client.queue.clear()
            client.queue.extend(queue_snapshot)

            restored = False
            if current_snapshot is not None:
                item = dict(current_snapshot)
                item["start_seconds"] = position
                client.queue.insert(0, item)
                self._start_next_locked(client)
                restored = client.current is item

            self._set_watchdog_state(
                client,
                getattr(client, "current", None),
                self._watchdog_position(client, time.monotonic()),
                time.monotonic(),
                0,
            )

            title = (
                current_snapshot.get("title")
                if current_snapshot is not None
                else None
            )
            return {
                "restored": restored,
                "title": title,
                "position_ms": int(position * 1000),
                "queue": len(client.queue),
            }

    async def stop(self, index: int) -> None:
        """Clear the queue, stop playback and disconnect the voice client."""

        client = self._clients.get(index)
        if client is None:
            return

        async with client.lock:
            client.queue.clear()
            client.current = None
            client.last_error = None

            voice = self._voice_for(client)
            if voice is not None:
                with contextlib.suppress(Exception):
                    voice.stop()
                with contextlib.suppress(Exception):
                    await voice.disconnect(force=True)

            self._retire_source(client)
            client.guild_id = None
            client.channel_id = None

        # Free the audio gateway as well: Stop must leave no second session
        # behind.  ``_cleanup_session`` re-checks state and never raises.
        await self._cleanup_session(index)

    def state(self) -> dict[str, dict[str, Any]]:
        """Return a dashboard-friendly snapshot keyed by token index."""

        snapshot: dict[str, dict[str, Any]] = {}
        now = time.monotonic()
        for index, client in list(self._clients.items()):
            current = getattr(client, "current", None)
            queue = getattr(client, "queue", []) or []
            started_at = getattr(client, "started_at", None)
            position_ms = 0
            if isinstance(current, dict):
                position_ms = max(
                    0,
                    int(
                        (_coerce_duration(current.get("start_seconds")) or 0.0)
                        * 1000
                    ),
                )
                if isinstance(started_at, (int, float)) and not isinstance(
                    started_at, bool
                ):
                    position_ms += max(0, int((now - started_at) * 1000))
            length_ms = None
            if isinstance(current, dict):
                duration = _coerce_duration(current.get("duration"))
                if duration is not None:
                    length_ms = int(duration * 1000)
            if length_ms and position_ms >= length_ms:
                position_ms %= length_ms
            active_filters = getattr(client, "active_filters", None)
            if isinstance(active_filters, str) or not isinstance(
                active_filters, (set, frozenset, list, tuple)
            ):
                active_filters = ()
            bass_level = getattr(client, "bass_level", 10)
            if isinstance(bass_level, bool) or not isinstance(bass_level, int):
                bass_level = 10
            volume_pct = getattr(client, "volume_pct", 100)
            if isinstance(volume_pct, bool) or not isinstance(volume_pct, int):
                volume_pct = 100
            snapshot[str(index)] = {
                "playing": bool(current),
                "title": current.get("title") if isinstance(current, dict) else None,
                "queue": [
                    item.get("title")
                    for item in queue
                    if isinstance(item, dict)
                ],
                "guild_id": getattr(client, "guild_id", None),
                "channel_id": getattr(client, "channel_id", None),
                "loop_mode": getattr(client, "loop_mode", None) or "off",
                "filters": sorted(
                    name for name in active_filters if isinstance(name, str)
                ),
                "bass_level": bass_level,
                "volume_pct": volume_pct,
                "position_ms": position_ms,
                "length_ms": length_ms,
            }
        return snapshot

    def health(self) -> dict[str, Any]:
        """Return a non-raising snapshot of the audio dependencies."""

        try:
            ffmpeg_ok, detail = ffmpeg_available()
        except Exception as exc:  # defensive: health must never raise
            ffmpeg_ok, detail = False, f"ffmpeg availability check failed: {exc}"

        return {
            "ok": bool(ffmpeg_ok),
            "ffmpeg": detail if ffmpeg_ok else None,
            "reason": None if ffmpeg_ok else (detail or "ffmpeg is not available"),
            "yt_dlp": yt_dlp is not None,
        }

    async def close_all(self) -> None:
        """Stop and close every audio client (bot shutdown/reload)."""

        await self._stop_watchdog()

        for index in list(self._clients):
            try:
                await self.stop(index)
            except Exception:
                client = self._clients.get(index)
                label = (
                    self._client_label(client)
                    if client is not None
                    else f"#{index}"
                )
                logger.exception("Voice audio %s stop failed during close", label)
            client = self._clients.pop(index, None)
            if client is None:
                continue
            try:
                await self._close_client(client)
            except Exception:
                logger.exception(
                    "Voice audio %s close failed",
                    self._client_label(client),
                )


audio_streamer = AudioStreamer()


def token_label(index: int, manager: Any = None) -> str:
    """Human label for a token index: ``#0 (alice)`` when a name is known."""
    name = None
    if manager is not None:
        try:
            name = getattr(manager.get_gateway(index), "username", None)
        except Exception:
            name = None
    if not name:
        try:
            name = audio_streamer.client_name(index)
        except Exception:
            name = None
    return f"#{index} ({name})" if name else f"#{index}"
