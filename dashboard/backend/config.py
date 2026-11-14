"""Configuration loading for the dashboard backend.

The real configuration lives next to this module in ``config.json``.  The
backend reads that file and can add/remove entries from the repository-root
``voice_token`` pool; copy ``config.example.json`` and fill in credentials
manually.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors ``main.py``: ``PREFIX = config.get('prefix', '.')``.
DEFAULT_PREFIX = "."

DEFAULT_CONFIG: dict[str, Any] = {
    "api_host": "127.0.0.1",
    "api_port": 8765,
    "allowed_origins": ["http://127.0.0.1:4000", "http://localhost:4000"],
    "bot_token": "",
    "application_id": "",
    "guild_id": "",
}

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
ROOT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"

_ROOT_CONFIG_LOCK = threading.Lock()


def load_root_bot_token() -> str:
    """Read the self-bot token from the repository root config, if present."""

    try:
        raw = json.loads(ROOT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""

    token = raw.get("token") if isinstance(raw, dict) else None
    return token.strip() if isinstance(token, str) else ""


def load_root_voice_tokens() -> list[str]:
    """Read the voice token pool from the repository root config.

    Empty entries are preserved so token indexes keep matching the bot's
    ``voice_token`` array.
    """

    try:
        raw = json.loads(ROOT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    tokens = raw.get("voice_token") if isinstance(raw, dict) else None
    if not isinstance(tokens, list):
        return []
    return [
        token.strip() if isinstance(token, str) else ""
        for token in tokens
    ]


def _read_root_config() -> dict[str, Any] | None:
    """Read the root config object, or return ``None`` when it is unusable.

    Error messages intentionally contain only the path and exception type so a
    malformed file can never leak token contents into the logs.
    """

    try:
        raw = json.loads(ROOT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not read root config %s (%s)",
            ROOT_CONFIG_PATH,
            type(exc).__name__,
        )
        return None

    if not isinstance(raw, dict):
        logger.warning("Root config %s is not a JSON object", ROOT_CONFIG_PATH)
        return None
    return raw


def _write_root_config(raw: dict[str, Any]) -> bool:
    """Atomically replace the root config with ``raw``.

    The temporary file is created in the same directory so ``os.replace`` is
    atomic on the same filesystem.  Returns ``False`` instead of raising when
    the write fails.
    """

    directory = ROOT_CONFIG_PATH.parent
    temp_path: str | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_path = tempfile.mkstemp(
            prefix=f"{ROOT_CONFIG_PATH.name}.",
            suffix=".tmp",
            dir=str(directory),
        )
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, ROOT_CONFIG_PATH)
        return True
    except OSError as exc:
        logger.warning(
            "Could not write root config %s (%s)",
            ROOT_CONFIG_PATH,
            type(exc).__name__,
        )
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return False


def _update_root_config(mutator) -> bool:
    """Read-modify-write config.json with optimistic concurrency.

    ``mutator(data)`` returns the new dict, or None to abort.
    Retries when another process replaced the file between our read and write.
    """
    with _ROOT_CONFIG_LOCK:
        for attempt in range(5):
            try:
                raw = ROOT_CONFIG_PATH.read_text(encoding="utf-8")
            except OSError:
                return False
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return False
            if not isinstance(data, dict):
                return False
            updated = mutator(dict(data))
            if updated is None:
                return False
            try:
                current = ROOT_CONFIG_PATH.read_text(encoding="utf-8")
            except OSError:
                current = None
            if current != raw:
                time.sleep(0.01 * (attempt + 1))
                continue
            tmp = ROOT_CONFIG_PATH.with_name(ROOT_CONFIG_PATH.name + ".tmp")
            try:
                tmp.write_text(
                    json.dumps(updated, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(tmp, ROOT_CONFIG_PATH)
            except OSError:
                return False
            return True
        return False


def add_root_voice_token(token: str) -> bool:
    """Append ``token`` to the root config's ``voice_token`` list.

    Returns ``False`` for empty tokens or when the config cannot be read or
    written.  All other config keys are preserved.  Token contents are never
    logged.
    """

    if not isinstance(token, str):
        return False
    cleaned = token.strip()
    if not cleaned:
        return False

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        tokens = data.get("voice_token")
        if not isinstance(tokens, list):
            tokens = []
            data["voice_token"] = tokens
        tokens.append(cleaned)
        return data

    return _update_root_config(mutator)


def delete_root_voice_token(index: int) -> bool:
    """Remove the ``voice_token`` entry at ``index`` from the root config.

    Returns ``False`` for invalid indexes or when the config cannot be read or
    written.  All other config keys are preserved.  Token contents are never
    logged.
    """

    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        return False

    def mutator(data: dict[str, Any]) -> dict[str, Any] | None:
        tokens = data.get("voice_token")
        if not isinstance(tokens, list) or index >= len(tokens):
            return None
        del tokens[index]
        return data

    return _update_root_config(mutator)


def get_root_prefix() -> str:
    """Return the root config prefix, or the bot's default prefix.

    A stored prefix is only honoured when it is a non-empty string without
    whitespace; anything else falls back to :data:`DEFAULT_PREFIX`.
    """

    raw = _read_root_config()
    if raw is not None:
        prefix = raw.get("prefix")
        if (
            isinstance(prefix, str)
            and prefix
            and not any(char.isspace() for char in prefix)
        ):
            return prefix
    return DEFAULT_PREFIX


def set_root_prefix(prefix: str) -> bool:
    """Persist ``prefix`` to the root config.

    Validation matches the bot's ``change_prefix`` command: 1-5 characters
    after stripping, with no whitespace.  All other config keys are preserved
    and token contents are never logged.  Returns ``False`` for invalid input
    or when the config cannot be read or written.
    """

    if not isinstance(prefix, str):
        return False
    cleaned = prefix.strip()
    if not cleaned or len(cleaned) > 5:
        return False
    if any(char.isspace() for char in cleaned):
        return False

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        data["prefix"] = cleaned
        return data

    return _update_root_config(mutator)


def request_bot_reload() -> bool:
    """Ask the running bot to reload by writing ``data/reload.flag``.

    ``ROOT_CONFIG_PATH`` is resolved at call time so tests can point it at a
    temporary directory.  Returns ``False`` instead of raising on failure.
    """

    flag_path = ROOT_CONFIG_PATH.parent / "data" / "reload.flag"
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning(
            "Could not write reload flag %s (%s)",
            flag_path,
            type(exc).__name__,
        )
        return False


def _clean_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a complete config, using defaults for invalid/missing values."""
    config = copy.deepcopy(DEFAULT_CONFIG)

    api_host = raw.get("api_host")
    if isinstance(api_host, str) and api_host.strip():
        config["api_host"] = api_host.strip()

    if config["api_host"] not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            "SECURITY: dashboard api_host is %r, which is not loopback; "
            "the dashboard is exposed beyond this machine.",
            config["api_host"],
        )

    api_port = raw.get("api_port")
    if (
        isinstance(api_port, int)
        and not isinstance(api_port, bool)
        and 1 <= api_port <= 65535
    ):
        config["api_port"] = api_port

    origins = raw.get("allowed_origins")
    if isinstance(origins, list) and all(isinstance(origin, str) for origin in origins):
        config["allowed_origins"] = [origin for origin in origins if origin]

    for key in ("bot_token", "application_id", "guild_id"):
        value = raw.get(key)
        if isinstance(value, str):
            config[key] = value

    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``config.json`` or return safe defaults.

    A missing file is normal.  Malformed files are logged without their
    contents (they may contain a token) and ignored.  This function never
    writes or creates a config file.
    """
    config_path = Path(path) if path is not None else CONFIG_PATH
    if not config_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not read dashboard config %s (%s); using defaults",
            config_path,
            type(exc).__name__,
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(raw, dict):
        logger.warning(
            "Dashboard config %s is not a JSON object; using defaults",
            config_path,
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    return _clean_config(raw)
