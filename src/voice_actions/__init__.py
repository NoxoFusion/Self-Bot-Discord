"""Registry for optional voice actions handled by extension modules.

A module in this package opts in by exposing:

* ``ACTIONS``: a list of dashboard action names (``list[str]``).
* ``handle(action, command, cog)``: an async callable that performs the action.

``cogs.voice.Voice._dashboard_commands`` calls :func:`dispatch_extra` for
actions that are not part of the built-in join/leave/stream/camera/reload set.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any], Any], Awaitable[None]]


def _iter_modules() -> list[ModuleType]:
    """Import and return every module in this package (except ``__init__``)."""

    modules: list[ModuleType] = []
    for info in pkgutil.iter_modules(__path__):
        module_name = f"{__name__}.{info.name}"
        try:
            modules.append(importlib.import_module(module_name))
        except Exception:
            logger.exception(
                "Voice action module %s failed to import; skipping",
                module_name,
            )
    return modules


def _discover_handlers() -> dict[str, Handler]:
    """Build the action -> handler map from the package modules."""

    handlers: dict[str, Handler] = {}
    for module in _iter_modules():
        actions = getattr(module, "ACTIONS", None)
        handle = getattr(module, "handle", None)
        if not isinstance(actions, (list, tuple)) or not callable(handle):
            logger.warning(
                "Voice action module %s must define ACTIONS and handle()",
                module.__name__,
            )
            continue
        for action in actions:
            if not isinstance(action, str):
                continue
            if action in handlers:
                logger.warning(
                    "Voice action %r already registered; ignoring duplicate in %s",
                    action,
                    module.__name__,
                )
                continue
            handlers[action] = handle
    return handlers


_HANDLERS: dict[str, Handler] = _discover_handlers()


async def dispatch_extra(action: str, command: dict, cog) -> bool:
    """Dispatch an action to an extension handler.

    Returns ``False`` when no module claims ``action`` so callers can ignore
    unknown actions. Handler failures are logged and reported as handled so a
    single broken extension cannot stop the dashboard command loop.
    """

    if not isinstance(action, str):
        return False
    handler = _HANDLERS.get(action)
    if handler is None:
        return False
    try:
        await handler(action, command, cog)
    except Exception:
        logger.exception("Voice action %r failed", action)
    return True
