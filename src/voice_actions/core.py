"""Placeholder for the voice action extension contract.

This module intentionally does nothing. It documents the interface that every
extension module in ``src.voice_actions`` must follow so the package is valid
even when no optional actions are installed:

* ``ACTIONS`` — a ``list[str]`` of dashboard action names the module handles.
* ``handle(action, command, cog)`` — an async callable invoked with the action
  name, the raw command dict from ``voice_commands.json``, and the ``Voice``
  cog instance.

Existing handlers (join/leave/stream/camera/reload) stay in ``cogs/voice.py``.
"""

ACTIONS = []


async def handle(action, command, cog):
    """No-op placeholder; extension modules override this contract."""

    return None
