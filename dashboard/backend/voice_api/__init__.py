"""Registry for optional dashboard voice API extension modules.

A module in this package opts in by exposing ``register(app)``. The function is
called once by :func:`register_voice_api` during ``create_app``.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger(__name__)

Register = Callable[[Any], None]


def _iter_modules() -> list[ModuleType]:
    """Import and return every module in this package (except ``__init__``)."""

    modules: list[ModuleType] = []
    for info in pkgutil.iter_modules(__path__):
        modules.append(importlib.import_module(f"{__name__}.{info.name}"))
    return modules


def register_voice_api(app) -> None:
    """Call ``register(app)`` once for every extension module in this package."""

    for module in _iter_modules():
        register = getattr(module, "register", None)
        if not callable(register):
            logger.warning(
                "Voice API module %s must define register(app)", module.__name__
            )
            continue
        register(app)


def protected_paths() -> set[str]:
    """Collect ``PROTECTED_PATHS`` declared by extension modules."""

    paths: set[str] = set()
    for module in _iter_modules():
        declared = getattr(module, "PROTECTED_PATHS", None)
        if isinstance(declared, (set, list, tuple)):
            paths.update(str(path) for path in declared)
    return paths


def protected_mutation_paths() -> set[str]:
    """Collect ``PROTECTED_MUTATION_PATHS`` declared by extension modules."""

    paths: set[str] = set()
    for module in _iter_modules():
        declared = getattr(module, "PROTECTED_MUTATION_PATHS", None)
        if isinstance(declared, (set, list, tuple)):
            paths.update(str(path) for path in declared)
    return paths
