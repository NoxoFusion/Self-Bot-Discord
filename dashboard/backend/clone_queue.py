"""JSON-file command queue and result store for dashboard-driven clones."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


_RESULT_TTL_SECONDS = 24 * 60 * 60


def _prune_results(results: dict[str, Any]) -> None:
    """Drop results last updated more than 24 hours ago."""
    cutoff = time.time() - _RESULT_TTL_SECONDS
    for key, value in list(results.items()):
        if not isinstance(value, dict):
            continue
        updated_at = value.get("updated_at")
        if isinstance(updated_at, (int, float)) and updated_at < cutoff:
            del results[key]


class CloneCommandQueue:
    """Append clone requests for the running bot's Utility cog."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def new_request_id() -> str:
        return uuid.uuid4().hex

    def enqueue(self, command: dict[str, Any]) -> None:
        directory = self.path.parent / f"{self.path.stem}.spool"
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns():020d}_{uuid.uuid4().hex}.json"
        temp = directory / f".{name}.tmp"
        temp.write_text(
            json.dumps(command, ensure_ascii=False), encoding="utf-8"
        )
        temp.replace(directory / name)


class CloneResultStore:
    """Read/write clone progress and results by request ID."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, request_id: str, status: str, message: str = "") -> None:
        results = _read_json(self.path, {})
        if not isinstance(results, dict):
            results = {}
        _prune_results(results)
        results[request_id] = {
            "status": status,
            "message": message,
            "updated_at": time.time(),
        }
        _write_json(self.path, results)

    def read(self, request_id: str) -> dict[str, Any] | None:
        results = _read_json(self.path, {})
        if not isinstance(results, dict):
            return None
        result = results.get(request_id)
        return result if isinstance(result, dict) else None
