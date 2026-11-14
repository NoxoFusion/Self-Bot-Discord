"""Local dashboard backend for the self-bot control panel.

This package is intentionally independent from the Discord bot runtime.  The
first slice exposes an authenticated local HTTP API and persists dashboard
settings, but the bot adapter is offline.
"""

__version__ = "0.1.0"
