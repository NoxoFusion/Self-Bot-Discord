"""Fan-out hub for dashboard WebSocket clients.

The hub is deliberately dependency-free: it only relies on the standard
library and the small ``send_str``/``close``/``closed`` surface exposed by
aiohttp's ``WebSocketResponse`` (or any test double that mimics it).
"""

from __future__ import annotations

import json
from typing import Any


class WsHub:
    """Track connected sockets and broadcast JSON payloads to all of them."""

    def __init__(self) -> None:
        self._sockets: set[Any] = set()

    def __len__(self) -> int:
        return len(self._sockets)

    @property
    def sockets(self) -> tuple[Any, ...]:
        """Return a snapshot of the connected sockets (for tests/diagnostics)."""

        return tuple(self._sockets)

    def add(self, ws: Any) -> None:
        self._sockets.add(ws)

    def discard(self, ws: Any) -> None:
        self._sockets.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        """Serialize ``payload`` once and send it to every live socket.

        Sockets that are already closed or whose ``send_str`` raises are
        dropped so a single dead client cannot break the broadcast.
        """

        message = json.dumps(payload)
        for ws in tuple(self._sockets):
            if getattr(ws, "closed", False):
                self.discard(ws)
                continue
            try:
                await ws.send_str(message)
            except Exception:
                self.discard(ws)

    async def close_all(self) -> None:
        """Close and forget every tracked socket."""

        for ws in tuple(self._sockets):
            self.discard(ws)
            try:
                await ws.close()
            except Exception:
                pass
