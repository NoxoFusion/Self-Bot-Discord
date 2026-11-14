"""Startup hygiene: force every automation feature OFF on process start.

Settings survive restarts; *enablement* does not.  Users turn features on
explicitly (dashboard or commands) after the bot is running, so a fresh start
never resumes broadcasting, auto-replies or reactions on its own.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = REPO_ROOT / "data" / "state.json"
DEFAULT_RUNTIME_PATH = REPO_ROOT / "dashboard" / "backend" / "runtime_state.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> bool:
    """Atomic write; returns False instead of raising."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(
                handle_fd, "w", encoding="utf-8", newline="\n"
            ) as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            return True
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.warning(
            "Startup reset: could not write %s (%s)",
            path,
            type(exc).__name__,
        )
        return False


def _reset_bot_state(state: dict[str, Any]) -> list[str]:
    """Clear bot-side enablement, keeping every user setting."""

    changed: list[str] = []

    # AFK: keep the reason, only disable the reply behaviour.
    if state.get("afk_enabled") is not False:
        state["afk_enabled"] = False
        changed.append("afk")

    auto = state.get("auto")
    if isinstance(auto, dict):
        # Auto-response triggers stay; the cog gates on this flag.
        if auto.get("ar_enabled") is not False:
            auto["ar_enabled"] = False
            changed.append("auto_responses")
        config = auto.get("auto_mess_config")
        if isinstance(config, dict) and config.get("active"):
            config["active"] = False
            changed.append("auto_mess")

    reactions = state.get("reactions")
    if isinstance(reactions, dict) and reactions.get("enabled") is not False:
        reactions["enabled"] = False
        changed.append("reactions")

    return changed


def _reset_dashboard_state(state: dict[str, Any]) -> list[str]:
    """Clear dashboard-side enablement, keeping every user setting."""

    changed: list[str] = []
    for section in ("automation", "afk", "reactions"):
        data = state.get(section)
        if isinstance(data, dict) and data.get("enabled"):
            data["enabled"] = False
            changed.append(section)
    return changed


def reset_features_to_off(
    state_path: Path | str | None = None,
    runtime_path: Path | str | None = None,
) -> dict[str, Any]:
    """Force every automation feature OFF while keeping user settings.

    Returns ``{"state": [...], "runtime": [...], "skipped": [...]}``.
    Never raises: a broken file is logged and skipped.
    """

    summary: dict[str, Any] = {"state": [], "runtime": [], "skipped": []}

    try:
        bot_path = (
            Path(state_path) if state_path is not None else DEFAULT_STATE_PATH
        )
        bot_state = _read_json(bot_path)
        if bot_state is None:
            summary["skipped"].append("state.json")
        else:
            changed = _reset_bot_state(bot_state)
            if changed and _write_json(bot_path, bot_state):
                summary["state"] = changed
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Startup reset: state.json failed (%s)", type(exc).__name__
        )

    try:
        dash_path = (
            Path(runtime_path)
            if runtime_path is not None
            else DEFAULT_RUNTIME_PATH
        )
        dash_state = _read_json(dash_path)
        if dash_state is None:
            summary["skipped"].append("runtime_state.json")
        else:
            changed = _reset_dashboard_state(dash_state)
            if changed and _write_json(dash_path, dash_state):
                summary["runtime"] = changed
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Startup reset: runtime_state.json failed (%s)",
            type(exc).__name__,
        )

    return summary
