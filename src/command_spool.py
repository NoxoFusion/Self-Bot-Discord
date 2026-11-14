"""Per-command spool shared by the dashboard producer and the bot consumer.

Producers write one uniquely named JSON file per command into a spool
directory.  Consumers unlink each file *before* yielding it, so a command is
executed at most once even if the consumer crashes mid-run.  A legacy shared
list file (``*_commands.json``) is drained once for migration.

This module is stdlib-only and uses no shared-file writes, so producers and
consumers can run in different processes without read-modify-write races.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def spool_dir(queue_path: Path) -> Path:
    """Return the spool directory that belongs to ``queue_path``."""

    queue_path = Path(queue_path)
    return queue_path.parent / f"{queue_path.stem}.spool"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def drain(queue_path: Path) -> Iterator[dict[str, Any]]:
    """Yield queued commands, removing each one before it is handed out.

    The legacy shared file is consumed first (once), then every ``*.json``
    file in the spool directory in filename order.  Malformed entries are
    logged by file name and skipped; their contents are never logged.
    """

    queue_path = Path(queue_path)
    legacy = queue_path
    if legacy.exists():
        payload = _read_json(legacy)
        try:
            legacy.unlink()
        except OSError:
            # Leave the file for the next tick rather than risk yielding the
            # same commands twice.
            logger.warning("Could not remove legacy command file %s", legacy.name)
        else:
            if isinstance(payload, list):
                for command in payload:
                    if isinstance(command, dict):
                        yield command
                    else:
                        logger.warning(
                            "Skipping malformed legacy command in %s", legacy.name
                        )
            else:
                logger.warning(
                    "Skipping malformed legacy command file %s", legacy.name
                )

    for path in sorted(spool_dir(queue_path).glob("*.json")):
        payload = _read_json(path)
        try:
            path.unlink()
        except OSError:
            # Do not yield a command that is still on disk; the next tick
            # would hand it out a second time.
            logger.warning("Could not remove command file %s", path.name)
            continue
        if isinstance(payload, dict):
            yield payload
        else:
            logger.warning("Skipping malformed command file %s", path.name)
