"""Small JSON state store with atomic writes and an async lock."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)

DEFAULT_STATE: dict[str, Any] = {
    "automation": {
        "enabled": False,
        "triggers": [],
        "broadcaster": {
            "enabled": False,
            "mode": "time",
            "value": 60,
            "channel_id": "",
        },
        "pool": [],
    },
    "afk": {
        "enabled": False,
        "reason": "",
        "cooldown": 10,
        "reply_mentions": True,
        "reply_dms": True,
    },
    "reactions": {
        "enabled": False,
        "target": "user",
        "user_id": "",
        "channel_id": "",
        "emojis": [],
        "cooldown": 3,
    },
}

Mutator = Callable[
    [dict[str, Any]],
    Union[dict[str, Any], None, Awaitable[Union[dict[str, Any], None]]],
]


def deep_merge(defaults: Any, override: Any) -> Any:
    """Merge ``override`` over ``defaults`` recursively.

    Dictionaries are merged key by key.  Lists and scalar values from
    ``override`` replace the default.  Extra keys in ``override`` are kept so
    future state fields are not silently discarded.
    """
    if isinstance(defaults, dict) and isinstance(override, dict):
        merged = copy.deepcopy(defaults)
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


class StateStore:
    """JSON-backed state with serialized, atomic writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def load(self) -> dict[str, Any]:
        """Read state, deep-merging it over the defaults."""
        async with self._lock:
            return await self._load_unlocked()

    async def save(self, data: dict[str, Any]) -> dict[str, Any]:
        """Replace state with ``data`` and return the merged saved state."""
        if not isinstance(data, dict):
            raise TypeError("state must be a dict")
        async with self._lock:
            merged = deep_merge(DEFAULT_STATE, data)
            await self._write_unlocked(merged)
            return copy.deepcopy(merged)

    async def update(self, mutator: Mutator) -> dict[str, Any]:
        """Read, mutate, and save state while holding the lock.

        ``mutator`` may mutate the passed dict in place and return ``None``,
        or return a replacement dict.  It may also be an async callable.
        """
        if not callable(mutator):
            raise TypeError("mutator must be callable")

        async with self._lock:
            current = await self._load_unlocked()
            result = mutator(current)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                result = current
            if not isinstance(result, dict):
                raise TypeError("mutator must return a dict or None")

            merged = deep_merge(DEFAULT_STATE, result)
            await self._write_unlocked(merged)
            return copy.deepcopy(merged)

    async def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_STATE)

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "State file %s is unreadable or corrupt (%s); using defaults",
                self.path,
                type(exc).__name__,
            )
            return copy.deepcopy(DEFAULT_STATE)

        if not isinstance(raw, dict):
            logger.warning(
                "State file %s does not contain a JSON object; using defaults",
                self.path,
            )
            return copy.deepcopy(DEFAULT_STATE)

        return deep_merge(DEFAULT_STATE, raw)

    async def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
