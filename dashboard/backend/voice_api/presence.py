"""Presence API: main-account rich presence config plus apply/clear commands.

The dashboard owns ``data/rich_presence.json``, the single entry shared with
the bot's existing presence system (:mod:`cogs.presence`) and with ``main.py``
for the identify ``service`` spoof.  Mutations validate and persist the entry,
then enqueue a command for the running bot; the bot performs the actual
Discord presence update.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import re
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from aiohttp import web

from .. import config as backend_config
from ..app import (
    _is_digits,
    _read_json,
    _validation_error,
    _voice_queue_or_error,
)

logger = logging.getLogger(__name__)

# Serializes the upload cache read-modify-write across concurrent requests.
_UPLOAD_CACHE_LOCK = asyncio.Lock()

CONFIG_PATH = "/api/v1/presence/config"
APPLY_PATH = "/api/v1/presence/apply"
CLEAR_PATH = "/api/v1/presence/clear"
SONGS_PATH = "/api/v1/presence/songs"
SONGS_RESOLVE_PATH = "/api/v1/presence/songs/resolve"
YOUTUBE_RESOLVE_PATH = "/api/v1/presence/youtube/resolve"
UPLOAD_PATH = "/api/v1/presence/upload-image"

PROTECTED_PATHS = {CONFIG_PATH, SONGS_PATH}
PROTECTED_MUTATION_PATHS = {
    CONFIG_PATH,
    APPLY_PATH,
    CLEAR_PATH,
    SONGS_PATH,
    SONGS_RESOLVE_PATH,
    YOUTUBE_RESOLVE_PATH,
    UPLOAD_PATH,
}

STATUSES = {"online", "idle", "dnd", "invisible"}
TYPES = {"playing", "streaming", "listening", "watching", "competing"}
PLATFORMS = {
    "desktop",
    "xbox",
    "samsung",
    "ios",
    "android",
    "embedded",
    "ps4",
    "ps5",
    "meta",
    "meta_quest",
}
MODES = {"spotify", "custom"}
MAX_ACTIVITIES = 3

NAME_MAX_LENGTH = 128
TEXT_MAX_LENGTH = 128
IMAGE_MAX_LENGTH = 2048
BUTTON_LABEL_MAX_LENGTH = 32
BUTTON_URL_MAX_LENGTH = 512
APPLICATION_ID_MAX_LENGTH = 32
STREAM_URL_MAX_LENGTH = 512
MAX_BUTTONS = 2
ELAPSED_HOURS_MIN = 0.0
ELAPSED_HOURS_MAX = 8760.0
ELAPSED_HOURS_DEFAULT = 1.0
END_MINUTES_MIN = 1.0
END_MINUTES_MAX = 1440.0
END_MINUTES_DEFAULT = 30.0
DURATION_MINUTES_MAX = 1440.0

MAX_SONGS = 100
SONG_NAME_MAX_LENGTH = 200
SONG_ARTIST_MAX_LENGTH = 200
SONG_ALBUM_MAX_LENGTH = 200
SONG_DURATION_MIN_MS = 1000
SONG_DURATION_MAX_MS = 3_600_000
SONG_IMAGE_MAX_LENGTH = 128
TRACK_ID_LENGTH = 22

TRACK_ID_RE = re.compile(rf"^[A-Za-z0-9]{{{TRACK_ID_LENGTH}}}$")
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
IMAGE_HASH_RE = re.compile(
    rf"^[A-Za-z0-9]{{1,{SONG_IMAGE_MAX_LENGTH}}}$"
)
SPOTIFY_IMAGE_PREFIX = "https://i.scdn.co/image/"
SPOTIFY_EMBED_URL = "https://open.spotify.com/embed/track/{track_id}"
SPOTIFY_OEMBED_URL = (
    "https://open.spotify.com/oembed?url="
    "https://open.spotify.com/track/{track_id}"
)
YOUTUBE_OEMBED_URL = (
    "https://noembed.com/embed?url="
    "https://www.youtube.com/watch?v={video_id}"
)
SPOTIFY_FETCH_TIMEOUT = 8
MAX_HTTP_BYTES = 1024 * 1024
UPLOAD_MAX_BYTES = 700 * 1024
UPLOAD_TIMEOUT = 15
UPLOAD_CACHE_MAX = 200
UPLOAD_FILENAME_MAX_LENGTH = 128
CATBOX_UPLOAD_URL = "https://catbox.moe/user/api.php"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
    re.DOTALL,
)

LEGACY_ACTIVITY_KEYS = (
    "application_id",
    "type",
    "platform",
    "name",
    "details",
    "state",
    "duration",
    "large_image",
    "large_text",
    "small_image",
    "small_text",
    "buttons",
)


def _default_config() -> dict[str, Any]:
    """Return a fresh default single-entry presence config."""

    return {
        "enabled": True,
        "mode": "custom",
        "status": "online",
        "service": "",
        "activities": [],
    }


def _presence_path() -> Path:
    """Return the presence config path, resolved at call time for tests."""

    return (
        Path(backend_config.ROOT_CONFIG_PATH).resolve().parent
        / "data"
        / "rich_presence.json"
    )


def _clean_mode(value: Any) -> str:
    """Return a supported mode, falling back to ``custom``."""

    mode = str(value or "custom").lower()
    return mode if mode in MODES else "custom"


def _clean_status(value: Any) -> str:
    """Return a supported status, falling back to ``online``."""

    status = str(value or "online").lower()
    return status if status in STATUSES else "online"


def _clean_service(value: Any) -> str:
    """Return a supported identify service, falling back to empty."""

    service = str(value or "").lower().strip()
    return service if service in PLATFORMS else ""


def _is_utf8_safe(value: str) -> bool:
    """Return ``False`` when ``value`` cannot be encoded as UTF-8."""

    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _normalized_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the non-activity fields of a single presence entry."""

    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        enabled = True
    return {
        "enabled": enabled,
        "mode": _clean_mode(raw.get("mode")),
        "status": _clean_status(raw.get("status")),
        "service": _clean_service(raw.get("service")),
    }


def _legacy_activity(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the single activity that preserves the legacy flat display."""

    activity_type = str(raw.get("type") or "listening").lower()
    if activity_type not in TYPES:
        activity_type = "listening"

    platform = raw.get("platform")
    name = platform.strip() if isinstance(platform, str) else ""
    if not name:
        name = "Discord"

    legacy_name = raw.get("name")
    details = legacy_name.strip() if isinstance(legacy_name, str) else ""
    legacy_details = raw.get("details")
    state = legacy_details.strip() if isinstance(legacy_details, str) else ""

    candidate: dict[str, Any] = {
        "type": activity_type,
        "name": name,
        "details": details,
        "state": state,
        "show_elapsed": True,
        "elapsed_hours": 1,
    }

    application_id = raw.get("application_id")
    if _is_digits(application_id):
        candidate["application_id"] = application_id

    for key in ("large_image", "large_text", "small_image", "small_text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            candidate[key] = value.strip()

    buttons = _clean_buttons(raw.get("buttons"))
    if buttons:
        candidate["buttons"] = buttons

    clean, _errors = _validate_activity(candidate, 0)
    if clean is None:
        clean = {
            "type": "listening",
            "name": "Discord",
            "show_elapsed": True,
            "elapsed_hours": 1.0,
        }
    return clean


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert the legacy flat config into a single custom entry."""

    return {
        "enabled": True,
        "mode": "custom",
        "status": _clean_status(raw.get("status")),
        "service": _clean_service(raw.get("service")),
        "activities": [_legacy_activity(raw)],
    }


def _read_config() -> dict[str, Any]:
    """Return the stored presence entry, migrating the legacy flat shape."""

    try:
        raw = json.loads(_presence_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_config()
    if not isinstance(raw, dict):
        return _default_config()

    activities = raw.get("activities")
    if isinstance(activities, list) and activities:
        entry = _normalized_entry(raw)

        cleaned: list[dict[str, Any]] = []
        for index, activity in enumerate(activities[:MAX_ACTIVITIES]):
            clean_activity, _errors = _validate_activity(activity, index)
            if clean_activity is not None:
                cleaned.append(clean_activity)

        entry["activities"] = cleaned
        return entry

    if "activities" in raw or "mode" in raw or "enabled" in raw:
        entry = _normalized_entry(raw)
        entry["activities"] = []
        return entry

    if any(key in raw for key in LEGACY_ACTIVITY_KEYS):
        return _migrate_legacy(raw)

    return _default_config()


def _write_config(config: dict[str, Any]) -> bool:
    """Atomically replace the presence config, returning ``False`` on error."""

    path = _presence_path()
    temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        return True
    except (OSError, UnicodeError) as exc:
        logger.warning(
            "Could not write presence config %s (%s)",
            path,
            type(exc).__name__,
        )
        try:
            temp_path.unlink()
        except OSError:
            pass
        return False


def _songs_path() -> Path:
    """Return the Spotify songs path, resolved at call time for tests."""

    return (
        Path(backend_config.ROOT_CONFIG_PATH).resolve().parent
        / "data"
        / "songs.json"
    )


def _upload_cache_path() -> Path:
    """Return the image upload cache path, resolved at call time for tests."""

    return (
        Path(backend_config.ROOT_CONFIG_PATH).resolve().parent
        / "data"
        / "upload_cache.json"
    )


def _extract_track_id(value: Any) -> str | None:
    """Return the bare 22-character track ID in ``value``, or ``None``."""

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if TRACK_ID_RE.fullmatch(candidate):
        return candidate

    prefix = "spotify:track:"
    if candidate.startswith(prefix):
        track_id = candidate[len(prefix) :]
        return track_id if TRACK_ID_RE.fullmatch(track_id) else None

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() != "open.spotify.com":
        return None
    match = re.fullmatch(
        rf"/track/([A-Za-z0-9]{{{TRACK_ID_LENGTH}}})/?", parsed.path
    )
    return match.group(1) if match is not None else None


def _normalize_image_url(value: Any) -> str:
    """Return a bare Spotify cover hash for an ``i.scdn.co`` URL."""

    if not isinstance(value, str):
        return ""
    image = value.strip()
    if image.startswith(SPOTIFY_IMAGE_PREFIX):
        image = image[len(SPOTIFY_IMAGE_PREFIX) :]
    return image if IMAGE_HASH_RE.fullmatch(image) else ""


def _extract_youtube_id(value: str) -> str | None:
    """Return the bare 11-character YouTube video ID in ``value``, or ``None``."""

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if YOUTUBE_ID_RE.fullmatch(candidate):
        return candidate

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "youtu.be":
        video_id = parsed.path.strip("/")
        return video_id if YOUTUBE_ID_RE.fullmatch(video_id) else None

    if host not in ("youtube.com", "music.youtube.com"):
        return None

    path = parsed.path.rstrip("/")
    if path == "/watch":
        values = parse_qs(parsed.query).get("v")
        if not values:
            return None
        video_id = values[0]
        return video_id if YOUTUBE_ID_RE.fullmatch(video_id) else None

    for prefix in ("/shorts/", "/embed/", "/live/"):
        if path.startswith(prefix):
            video_id = path[len(prefix) :]
            return video_id if YOUTUBE_ID_RE.fullmatch(video_id) else None
    return None


def _normalize_youtube_image(value: str) -> str:
    """Return ``youtube:<id>`` for a YouTube video URL, else ``value``.

    Only http(s) URLs are rewritten: a bare 11-character string in an image
    field is a Discord asset name (e.g. ``large_image``), not a video id.
    """

    if not value:
        return value
    if value.startswith("youtube:"):
        return value
    if not value.lower().startswith(("http://", "https://")):
        return value
    video_id = _extract_youtube_id(value)
    if video_id is not None:
        return f"youtube:{video_id}"
    return value


def _clean_song(
    raw: Any, index: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one ``data/songs.json`` entry."""

    prefix = f"songs[{index}]"
    if not isinstance(raw, dict):
        return None, [f"{prefix} must be an object"]

    errors: list[str] = []

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{prefix}.name must be a non-empty string")
        name = ""
    else:
        name = name.strip()
        if not _is_utf8_safe(name):
            errors.append(f"{prefix}.name contains invalid characters")
        if len(name) > SONG_NAME_MAX_LENGTH:
            errors.append(
                f"{prefix}.name must be at most "
                f"{SONG_NAME_MAX_LENGTH} characters"
            )

    artist = raw.get("artist", "")
    if artist is None:
        artist = ""
    if not isinstance(artist, str):
        errors.append(f"{prefix}.artist must be a string")
        artist = ""
    else:
        artist = artist.strip()
        if not _is_utf8_safe(artist):
            errors.append(f"{prefix}.artist contains invalid characters")
        if len(artist) > SONG_ARTIST_MAX_LENGTH:
            errors.append(
                f"{prefix}.artist must be at most "
                f"{SONG_ARTIST_MAX_LENGTH} characters"
            )

    raw_id = raw.get("id")
    if isinstance(raw_id, str) and not _is_utf8_safe(raw_id):
        errors.append(f"{prefix}.id contains invalid characters")
    track_id = _extract_track_id(raw_id)
    if track_id is None:
        errors.append(
            f"{prefix}.id must be a 22-character Spotify track ID"
        )

    duration_ms = 0
    raw_duration = raw.get("duration_ms")
    if isinstance(raw_duration, bool):
        errors.append(
            f"{prefix}.duration_ms must be an integer between "
            f"{SONG_DURATION_MIN_MS} and {SONG_DURATION_MAX_MS}"
        )
    else:
        try:
            duration_ms = int(raw_duration)
        except (TypeError, ValueError, OverflowError):
            errors.append(
                f"{prefix}.duration_ms must be an integer between "
                f"{SONG_DURATION_MIN_MS} and {SONG_DURATION_MAX_MS}"
            )
            duration_ms = 0
        else:
            if not SONG_DURATION_MIN_MS <= duration_ms <= SONG_DURATION_MAX_MS:
                errors.append(
                    f"{prefix}.duration_ms must be an integer between "
                    f"{SONG_DURATION_MIN_MS} and {SONG_DURATION_MAX_MS}"
                )
                duration_ms = 0

    image = ""
    raw_image = raw.get("image")
    if raw_image is not None:
        if not isinstance(raw_image, str):
            errors.append(
                f"{prefix}.image must be a Spotify image hash or "
                "https://i.scdn.co/image/ URL"
            )
        else:
            if not _is_utf8_safe(raw_image):
                errors.append(
                    f"{prefix}.image contains invalid characters"
                )
            image = _normalize_image_url(raw_image)
            if raw_image.strip() and not image:
                errors.append(
                    f"{prefix}.image must be a Spotify image hash or "
                    "https://i.scdn.co/image/ URL"
                )

    song: dict[str, Any] = {
        "name": name,
        "artist": artist,
        "id": track_id or "",
        "duration_ms": duration_ms,
        "image": image,
    }

    album = raw.get("album")
    if album is not None:
        if not isinstance(album, str):
            errors.append(f"{prefix}.album must be a string")
        else:
            if not _is_utf8_safe(album):
                errors.append(
                    f"{prefix}.album contains invalid characters"
                )
            album = album.strip()
            if len(album) > SONG_ALBUM_MAX_LENGTH:
                errors.append(
                    f"{prefix}.album must be at most "
                    f"{SONG_ALBUM_MAX_LENGTH} characters"
                )
            elif album:
                song["album"] = album

    return song, errors


def _read_songs() -> list[dict[str, Any]]:
    """Return valid songs from ``data/songs.json``, skipping bad entries."""

    try:
        raw = json.loads(_songs_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []

    songs: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        clean, errors = _clean_song(entry, index)
        if clean is not None and not errors:
            songs.append(clean)
    return songs


def _write_songs(songs: list[dict[str, Any]]) -> bool:
    """Atomically replace ``data/songs.json``, returning ``False`` on error."""

    path = _songs_path()
    temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if songs:
            body = (
                "[\n"
                + ",\n".join(
                    "  " + json.dumps(song, ensure_ascii=False)
                    for song in songs
                )
                + "\n]\n"
            )
        else:
            body = "[]\n"
        temp_path.write_text(body, encoding="utf-8")
        temp_path.replace(path)
        return True
    except (OSError, UnicodeError) as exc:
        logger.warning(
            "Could not write songs file %s (%s)",
            path,
            type(exc).__name__,
        )
        try:
            temp_path.unlink()
        except OSError:
            pass
        return False


def _detect_image_type(data: bytes) -> str | None:
    """Return the image type of ``data`` by magic bytes, or ``None``."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if (
        len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return "webp"
    return None


def _read_upload_cache() -> dict[str, str]:
    """Return the sha256-to-URL upload cache, tolerating a corrupt file."""

    try:
        raw = json.loads(_upload_cache_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _write_upload_cache(cache: dict[str, str]) -> bool:
    """Atomically replace the upload cache, returning ``False`` on error."""

    path = _upload_cache_path()
    temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        return True
    except (OSError, UnicodeError) as exc:
        logger.warning(
            "Could not write upload cache %s (%s)",
            path,
            type(exc).__name__,
        )
        try:
            temp_path.unlink()
        except OSError:
            pass
        return False


def _upload_to_catbox(data: bytes, filename: str) -> str | None:
    """Upload ``data`` to catbox.moe, returning the public URL or ``None``."""

    safe_name = (
        filename.replace('"', "").replace("\r", "").replace("\n", "").strip()
        or "image"
    )
    boundary = uuid4().hex
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="reqtype"\r\n'
        "\r\n"
        "fileupload\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="fileToUpload"; '
        f'filename="{safe_name}"\r\n'
        "Content-Type: image/png\r\n"
        "\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        CATBOX_UPLOAD_URL,
        data=head + data + tail,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": BROWSER_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=UPLOAD_TIMEOUT
        ) as response:
            payload = response.read(MAX_HTTP_BYTES)
    except Exception:
        logger.debug("Catbox upload failed", exc_info=True)
        return None
    url = payload.decode("utf-8", errors="replace").strip()
    return url if url.startswith("https://") else None


def _http_get_text(url: str) -> str:
    """Fetch ``url`` with a browser-like User-Agent."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(
        request, timeout=SPOTIFY_FETCH_TIMEOUT
    ) as response:
        payload = response.read(MAX_HTTP_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _fetch_spotify_embed(track_id: str) -> dict[str, Any] | None:
    """Fetch public Spotify metadata for one track, or ``None`` on failure."""

    if not isinstance(track_id, str) or not TRACK_ID_RE.fullmatch(track_id):
        return None

    try:
        html = _http_get_text(
            SPOTIFY_EMBED_URL.format(track_id=track_id)
        )
        match = NEXT_DATA_RE.search(html)
        if match is not None:
            payload = json.loads(match.group("data"))
            entity = payload["props"]["pageProps"]["state"]["data"]["entity"]
            name = entity.get("name")
            if isinstance(name, str) and name.strip():
                artist_names: list[str] = []
                artists = entity.get("artists")
                if isinstance(artists, list):
                    for artist in artists:
                        if not isinstance(artist, dict):
                            continue
                        artist_name = artist.get("name")
                        if (
                            isinstance(artist_name, str)
                            and artist_name.strip()
                        ):
                            artist_names.append(artist_name.strip())

                duration_ms = 0
                duration = entity.get("duration")
                if isinstance(duration, (int, float)) and not isinstance(
                    duration, bool
                ):
                    duration_ms = int(duration)
                duration_ms = min(
                    SONG_DURATION_MAX_MS,
                    max(SONG_DURATION_MIN_MS, duration_ms),
                )

                image = ""
                cover_art = entity.get("coverArt")
                if isinstance(cover_art, dict):
                    sources = cover_art.get("sources")
                    if isinstance(sources, list) and sources:
                        first_source = sources[0]
                        if isinstance(first_source, dict):
                            image = _normalize_image_url(
                                first_source.get("url")
                            )

                return {
                    "name": name.strip(),
                    "artist": ", ".join(artist_names),
                    "id": track_id,
                    "duration_ms": duration_ms,
                    "image": image,
                }
    except Exception:
        logger.debug(
            "Spotify embed lookup failed for %s", track_id, exc_info=True
        )

    try:
        payload = json.loads(
            _http_get_text(SPOTIFY_OEMBED_URL.format(track_id=track_id))
        )
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return {
                "name": title.strip(),
                "artist": "",
                "id": track_id,
                "duration_ms": SONG_DURATION_MIN_MS,
                "image": _normalize_image_url(payload.get("thumbnail_url")),
            }
    except Exception:
        logger.debug(
            "Spotify oEmbed lookup failed for %s", track_id, exc_info=True
        )

    return None


def _fetch_youtube_metadata(video_id: str) -> dict[str, Any] | None:
    """Fetch public YouTube metadata for one video, or ``None`` on failure."""

    if not isinstance(video_id, str) or not YOUTUBE_ID_RE.fullmatch(video_id):
        return None

    try:
        payload = json.loads(
            _http_get_text(YOUTUBE_OEMBED_URL.format(video_id=video_id))
        )
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            channel = payload.get("author_name")
            return {
                "title": title.strip(),
                "channel": (
                    channel.strip() if isinstance(channel, str) else ""
                ),
            }
    except Exception:
        logger.debug(
            "YouTube oEmbed lookup failed for %s", video_id, exc_info=True
        )

    return None


def _clean_optional_text(
    act: dict[str, Any],
    key: str,
    max_length: int,
    index: int,
    errors: list[str],
) -> str | None:
    """Return a trimmed optional string, or ``None`` when absent/invalid."""

    value = act.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"activities[{index}].{key} must be a string")
        return None
    if not _is_utf8_safe(value):
        errors.append(
            f"activities[{index}].{key} contains invalid characters"
        )
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        errors.append(
            f"activities[{index}].{key} must be at most "
            f"{max_length} characters"
        )
        return None
    return cleaned


def _clean_buttons(buttons: Any) -> list[dict[str, str]]:
    """Return the first two valid link buttons, skipping invalid entries."""

    if not isinstance(buttons, list):
        return []

    cleaned: list[dict[str, str]] = []
    for entry in buttons:
        if len(cleaned) >= MAX_BUTTONS:
            break
        if not isinstance(entry, dict):
            continue

        label = entry.get("label")
        url = entry.get("url")
        if not isinstance(label, str) or not isinstance(url, str):
            continue

        label = label.strip()
        url = url.strip()
        if not label or len(label) > BUTTON_LABEL_MAX_LENGTH:
            continue
        if not url or len(url) > BUTTON_URL_MAX_LENGTH:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue

        cleaned.append({"label": label, "url": url})
    return cleaned


def _clean_elapsed_hours(value: Any) -> float:
    """Return a finite elapsed-hours value clamped to the supported range."""

    if isinstance(value, bool):
        return ELAPSED_HOURS_DEFAULT
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return ELAPSED_HOURS_DEFAULT
    if not math.isfinite(hours):
        return ELAPSED_HOURS_DEFAULT
    return min(ELAPSED_HOURS_MAX, max(ELAPSED_HOURS_MIN, hours))


def _clean_end_minutes(value: Any) -> float:
    """Return a finite end-minutes value clamped to the supported range."""

    if isinstance(value, bool):
        return END_MINUTES_DEFAULT
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return END_MINUTES_DEFAULT
    if not math.isfinite(minutes):
        return END_MINUTES_DEFAULT
    return min(END_MINUTES_MAX, max(END_MINUTES_MIN, minutes))


def _clean_duration_minutes(value: Any) -> float:
    """Return a finite progress duration in minutes (0 = disabled)."""

    if isinstance(value, bool):
        return 0.0
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(minutes):
        return 0.0
    return min(DURATION_MINUTES_MAX, max(0.0, minutes))


def _validate_activity(
    act: Any, index: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one rich-presence activity entry."""

    if not isinstance(act, dict):
        return None, [f"activities[{index}] must be an object"]

    errors: list[str] = []
    prefix = f"activities[{index}]"

    activity_type = str(act.get("type") or "playing").lower()
    if activity_type not in TYPES:
        return None, [
            f"{prefix}.type must be one of: " + ", ".join(sorted(TYPES))
        ]

    name = act.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, [f"{prefix}.name must be a non-empty string"]
    name = name.strip()
    if len(name) > NAME_MAX_LENGTH:
        return None, [
            f"{prefix}.name must be at most {NAME_MAX_LENGTH} characters"
        ]
    if not _is_utf8_safe(name):
        errors.append(f"{prefix}.name contains invalid characters")

    cleaned: dict[str, Any] = {"type": activity_type, "name": name}

    application_id = act.get("application_id")
    if application_id not in (None, ""):
        if isinstance(application_id, str) and not _is_utf8_safe(
            application_id
        ):
            errors.append(
                f"{prefix}.application_id contains invalid characters"
            )
        if _is_digits(application_id):
            if len(application_id) > APPLICATION_ID_MAX_LENGTH:
                errors.append(
                    f"{prefix}.application_id must be at most "
                    f"{APPLICATION_ID_MAX_LENGTH} digits"
                )
            else:
                cleaned["application_id"] = application_id
        else:
            errors.append(
                f"{prefix}.application_id must be a digit string"
            )

    for key, max_length in (
        ("details", TEXT_MAX_LENGTH),
        ("state", TEXT_MAX_LENGTH),
        ("large_image", IMAGE_MAX_LENGTH),
        ("small_image", IMAGE_MAX_LENGTH),
        ("large_text", TEXT_MAX_LENGTH),
        ("small_text", TEXT_MAX_LENGTH),
    ):
        value = _clean_optional_text(act, key, max_length, index, errors)
        if value is not None:
            cleaned[key] = value

    for key in ("large_image", "small_image"):
        if key in cleaned:
            cleaned[key] = _normalize_youtube_image(cleaned[key])

    platform = act.get("platform")
    if isinstance(platform, str):
        platform = platform.lower().strip()
        if platform in PLATFORMS:
            cleaned["platform"] = platform

    if activity_type == "streaming":
        stream_url = act.get("url")
        if not isinstance(stream_url, str):
            errors.append(
                f"{prefix}.url must be a Twitch or "
                "YouTube URL for streaming activities"
            )
        else:
            stream_url = stream_url.strip()
            if not _is_utf8_safe(stream_url):
                errors.append(f"{prefix}.url contains invalid characters")
            elif not stream_url.startswith(
                (
                    "https://twitch.tv/",
                    "https://www.twitch.tv/",
                    "https://youtube.com/",
                    "https://www.youtube.com/",
                )
            ):
                errors.append(
                    f"{prefix}.url must be a Twitch or "
                    "YouTube URL for streaming activities"
                )
            elif len(stream_url) > STREAM_URL_MAX_LENGTH:
                errors.append(
                    f"{prefix}.url must be at most "
                    f"{STREAM_URL_MAX_LENGTH} characters"
                )
            else:
                cleaned["url"] = stream_url

    show_elapsed = act.get("show_elapsed", True)
    if not isinstance(show_elapsed, bool):
        errors.append(f"{prefix}.show_elapsed must be a boolean")
        show_elapsed = True
    cleaned["show_elapsed"] = show_elapsed
    cleaned["elapsed_hours"] = _clean_elapsed_hours(
        act.get("elapsed_hours", ELAPSED_HOURS_DEFAULT)
    )

    if activity_type in ("listening", "watching"):
        show_end = act.get("show_end", False)
        if not isinstance(show_end, bool):
            errors.append(f"{prefix}.show_end must be a boolean")
            show_end = False
        cleaned["show_end"] = show_end
        cleaned["end_minutes"] = _clean_end_minutes(
            act.get("end_minutes", END_MINUTES_DEFAULT)
        )
        duration_minutes = _clean_duration_minutes(
            act.get("duration_minutes", 0)
        )
        if duration_minutes > 0:
            cleaned["duration_minutes"] = duration_minutes

    raw_buttons = act.get("buttons")
    if isinstance(raw_buttons, list):
        for button_index, button in enumerate(raw_buttons):
            if not isinstance(button, dict):
                continue
            for key in ("label", "url"):
                value = button.get(key)
                if isinstance(value, str) and not _is_utf8_safe(value):
                    errors.append(
                        f"{prefix}.buttons[{button_index}].{key} "
                        "contains invalid characters"
                    )

    buttons = _clean_buttons(raw_buttons)
    if buttons:
        cleaned["buttons"] = buttons

    return cleaned, errors


def validate_presence_config(
    raw: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(clean_entry, errors)`` for one raw presence entry."""

    if not isinstance(raw, dict):
        return {}, ["config must be an object"]

    errors: list[str] = []

    for field in ("mode", "status", "service"):
        value = raw.get(field)
        if isinstance(value, str) and not _is_utf8_safe(value):
            errors.append(f"{field} contains invalid characters")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")
        enabled = True

    mode = str(raw.get("mode") or "custom").lower()
    if mode not in MODES:
        errors.append("mode must be one of: custom, spotify")
        mode = "custom"

    status = str(raw.get("status") or "online").lower()
    if status not in STATUSES:
        errors.append(
            "status must be one of: " + ", ".join(sorted(STATUSES))
        )
        status = "online"

    raw_service = raw.get("service")
    service = _clean_service(raw_service)
    if (
        isinstance(raw_service, str)
        and raw_service.strip()
        and service == ""
    ):
        errors.append(
            "service must be one of: " + ", ".join(sorted(PLATFORMS))
        )

    clean: dict[str, Any] = {
        "enabled": enabled,
        "mode": mode,
        "status": status,
        "service": service,
        "activities": [],
    }

    activities = raw.get("activities")
    if activities is None:
        activities = []
    if not isinstance(activities, list):
        errors.append("activities must be a list")
    elif len(activities) > MAX_ACTIVITIES:
        errors.append(
            f"activities must contain at most {MAX_ACTIVITIES} entries"
        )
    else:
        cleaned_activities: list[dict[str, Any]] = []
        for index, activity in enumerate(activities):
            clean_activity, activity_errors = _validate_activity(
                activity, index
            )
            errors.extend(activity_errors)
            if clean_activity is not None:
                cleaned_activities.append(clean_activity)

        if enabled and len({a["type"] for a in cleaned_activities}) != len(
            cleaned_activities
        ):
            errors.append(
                "activities must use distinct types — Discord displays "
                "only one activity per type"
            )
        clean["activities"] = cleaned_activities

    return clean, errors


async def get_presence_config(request: web.Request) -> web.Response:
    """Return the persisted presence entry."""

    return web.json_response({"config": _read_config()})


async def put_presence_config(request: web.Request) -> web.Response:
    """Validate, persist, and announce a new presence entry."""

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    config = body.get("config")
    if not isinstance(config, dict):
        return _validation_error(["config must be an object"])

    clean, errors = validate_presence_config(config)
    if errors:
        return _validation_error(errors)

    if not _write_config(clean):
        return web.json_response({"error": "config_write_failed"}, status=500)

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return web.json_response(
            {"ok": True, "config": clean, "queued": False}
        )

    queue.enqueue({"action": "presence_reload"})
    return web.json_response({"ok": True, "config": clean, "queued": True})


async def get_presence_songs(request: web.Request) -> web.Response:
    """Return the persisted Spotify song list."""

    return web.json_response({"songs": _read_songs()})


async def put_presence_songs(request: web.Request) -> web.Response:
    """Validate and persist the Spotify song list.

    The running bot reloads ``data/songs.json`` itself once its song
    queue empties, so no reload command is enqueued here.
    """

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    raw_songs = body.get("songs")
    if not isinstance(raw_songs, list):
        return _validation_error(["songs must be a list"])
    if len(raw_songs) > MAX_SONGS:
        return _validation_error(
            [f"songs must contain at most {MAX_SONGS} entries"]
        )

    songs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, raw_song in enumerate(raw_songs):
        clean_song, song_errors = _clean_song(raw_song, index)
        errors.extend(song_errors)
        if clean_song is not None and not song_errors:
            song_id = clean_song["id"]
            if song_id in seen_ids:
                errors.append(f"songs[{index}].id is duplicated")
            seen_ids.add(song_id)
            songs.append(clean_song)

    if errors:
        return _validation_error(errors)

    if not _write_songs(songs):
        return web.json_response({"error": "songs_write_failed"}, status=500)

    return web.json_response({"ok": True})


async def post_presence_songs_resolve(request: web.Request) -> web.Response:
    """Resolve a Spotify track URL into song metadata for the dashboard."""

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    track_id = _extract_track_id(body.get("url"))
    if track_id is None:
        return _validation_error(
            ["url must be a Spotify track URL or ID"]
        )

    loop = asyncio.get_running_loop()
    try:
        song = await loop.run_in_executor(
            None, _fetch_spotify_embed, track_id
        )
    except Exception:
        logger.debug(
            "Spotify resolve failed for %s", track_id, exc_info=True
        )
        song = None
    if not isinstance(song, dict):
        return web.json_response({"error": "resolve_failed"}, status=502)

    name = song.get("name")
    if not isinstance(name, str) or not name.strip():
        return web.json_response({"error": "resolve_failed"}, status=502)

    artist = song.get("artist")
    duration_ms = song.get("duration_ms")
    if isinstance(duration_ms, bool):
        duration_ms = 0
    else:
        try:
            duration_ms = int(duration_ms)
        except (TypeError, ValueError, OverflowError):
            duration_ms = 0
    duration_ms = min(
        SONG_DURATION_MAX_MS, max(SONG_DURATION_MIN_MS, duration_ms)
    )

    return web.json_response(
        {
            "song": {
                "name": name.strip(),
                "artist": artist.strip() if isinstance(artist, str) else "",
                "id": track_id,
                "duration_ms": duration_ms,
                "image": _normalize_image_url(song.get("image")),
            }
        }
    )


async def post_presence_youtube_resolve(request: web.Request) -> web.Response:
    """Resolve a YouTube URL into video metadata for the dashboard."""

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    video_id = _extract_youtube_id(body.get("url"))
    if video_id is None:
        return _validation_error(
            ["url must be a YouTube video URL or ID"]
        )

    loop = asyncio.get_running_loop()
    try:
        metadata = await loop.run_in_executor(
            None, _fetch_youtube_metadata, video_id
        )
    except Exception:
        logger.debug(
            "YouTube resolve failed for %s", video_id, exc_info=True
        )
        metadata = None
    if not isinstance(metadata, dict):
        return web.json_response({"error": "resolve_failed"}, status=502)

    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip():
        return web.json_response({"error": "resolve_failed"}, status=502)

    channel = metadata.get("channel")
    return web.json_response(
        {
            "video": {
                "video_id": video_id,
                "title": title.strip(),
                "channel": (
                    channel.strip() if isinstance(channel, str) else ""
                ),
                "image": f"youtube:{video_id}",
            }
        }
    )


async def post_presence_upload_image(request: web.Request) -> web.Response:
    """Upload a presence image to catbox.moe and return its public URL."""

    body = await _read_json(request)
    if not isinstance(body, dict):
        return _validation_error(["body must be a JSON object"])

    filename = body.get("filename")
    if (
        not isinstance(filename, str)
        or not filename.strip()
        or len(filename) > UPLOAD_FILENAME_MAX_LENGTH
    ):
        return _validation_error(
            [
                "filename must be a non-empty string of at most "
                f"{UPLOAD_FILENAME_MAX_LENGTH} characters"
            ]
        )

    encoded = body.get("data")
    if not isinstance(encoded, str):
        return web.json_response({"error": "invalid_image"}, status=400)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid_image"}, status=400)

    if not data or len(data) > UPLOAD_MAX_BYTES:
        return web.json_response({"error": "upload_too_large"}, status=400)

    if _detect_image_type(data) is None:
        return web.json_response({"error": "invalid_image"}, status=400)

    digest = hashlib.sha256(data).hexdigest()
    async with _UPLOAD_CACHE_LOCK:
        cache = _read_upload_cache()
        cached_url = cache.get(digest)
        if isinstance(cached_url, str) and cached_url.startswith("https://"):
            return web.json_response({"url": cached_url})

        loop = asyncio.get_running_loop()
        try:
            url = await loop.run_in_executor(
                None, _upload_to_catbox, data, filename.strip()
            )
        except Exception:
            logger.debug("Image upload failed", exc_info=True)
            url = None
        if not isinstance(url, str) or not url.startswith("https://"):
            return web.json_response({"error": "upload_failed"}, status=502)

        cache[digest] = url
        while len(cache) > UPLOAD_CACHE_MAX:
            cache.pop(next(iter(cache)))
        _write_upload_cache(cache)
    return web.json_response({"url": url})


async def _post_presence_command(
    request: web.Request, action: str
) -> web.Response:
    """Queue a presence command for the main bot account."""

    queue, error = _voice_queue_or_error(request)
    if error is not None:
        return error

    queue.enqueue({"action": action})
    return web.json_response({"queued": True})


async def post_presence_apply(request: web.Request) -> web.Response:
    """Queue applying the stored presence for the main account."""

    return await _post_presence_command(request, "presence_apply")


async def post_presence_clear(request: web.Request) -> web.Response:
    """Queue clearing the presence for the main account."""

    return await _post_presence_command(request, "presence_clear")


def register(app) -> None:
    """Attach the presence routes to the dashboard application."""

    app.router.add_get(CONFIG_PATH, get_presence_config)
    app.router.add_put(CONFIG_PATH, put_presence_config)
    app.router.add_get(SONGS_PATH, get_presence_songs)
    app.router.add_put(SONGS_PATH, put_presence_songs)
    app.router.add_post(SONGS_RESOLVE_PATH, post_presence_songs_resolve)
    app.router.add_post(YOUTUBE_RESOLVE_PATH, post_presence_youtube_resolve)
    app.router.add_post(UPLOAD_PATH, post_presence_upload_image)
    app.router.add_post(APPLY_PATH, post_presence_apply)
    app.router.add_post(CLEAR_PATH, post_presence_clear)
