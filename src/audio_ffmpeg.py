"""Resolve a usable ffmpeg executable for voice playback.

The free HidenCloud container is Linux/arm64, where ``imageio-ffmpeg`` has no
binary.  Voice playback therefore has to be able to use a system or static
ffmpeg, and a missing ffmpeg must never prevent the bot from booting.

Resolution order (first candidate that answers ``ffmpeg -version`` wins):

1. the ``FFMPEG_PATH`` environment variable
2. ``bin/ffmpeg`` (``bin/ffmpeg.exe`` on Windows) in the repository
3. ``ffmpeg`` on ``PATH``
4. ``imageio_ffmpeg.get_ffmpeg_exe()`` when that package is installed

The resolved path is cached for the lifetime of the process.  Call
:func:`reset_cache` after changing ``FFMPEG_PATH`` or installing a binary.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_MISSING_MESSAGE = (
    "ffmpeg not found. Set FFMPEG_PATH or place a static ffmpeg binary at "
    "bin/ffmpeg (see docs/DEPLOY-HIDENCLOUD.md)."
)

_cached_path: str | None = None


class AudioUnavailable(RuntimeError):
    """Raised when no usable ffmpeg executable can be found."""

    def __init__(self, message: str = _MISSING_MESSAGE) -> None:
        super().__init__(message)


def _probe(candidate: str) -> bool:
    """Return ``True`` when ``candidate -version`` exits successfully."""

    try:
        result = subprocess.run(
            [candidate, "-version"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    except Exception:  # defensive: a bad path must never break resolution
        return False
    return result.returncode == 0


def _bin_candidates() -> list[str]:
    candidates = [_REPO_ROOT / "bin" / "ffmpeg"]
    if os.name == "nt":
        candidates.append(_REPO_ROOT / "bin" / "ffmpeg.exe")
    return [str(path) for path in candidates]


def _imageio_candidate() -> str | None:
    """Return imageio-ffmpeg's executable, or ``None`` when unavailable."""

    try:
        import imageio_ffmpeg
    except Exception:  # optional dependency, including a broken install
        return None
    try:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    if isinstance(executable, str) and executable.strip():
        return executable.strip()
    return None


def _iter_candidates() -> Iterator[tuple[str, str]]:
    """Yield ``(source, executable)`` pairs in resolution order."""

    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path:
        yield "FFMPEG_PATH", env_path

    for path in _bin_candidates():
        yield "bin", path

    path_executable = shutil.which("ffmpeg")
    if path_executable:
        yield "PATH", path_executable

    # Import imageio_ffmpeg only after the cheaper candidates failed.
    imageio_executable = _imageio_candidate()
    if imageio_executable:
        yield "imageio-ffmpeg", imageio_executable


def resolve_ffmpeg() -> str:
    """Return the first ffmpeg executable that passes ``-version``.

    Raises :class:`AudioUnavailable` with an actionable message when no
    candidate works.  The successful path is cached.
    """

    global _cached_path
    if _cached_path is not None:
        return _cached_path

    for source, candidate in _iter_candidates():
        if _probe(candidate):
            _cached_path = candidate
            logger.info("Using ffmpeg from %s: %s", source, candidate)
            return candidate

    raise AudioUnavailable(_MISSING_MESSAGE)


def ffmpeg_available() -> tuple[bool, str | None]:
    """Return ``(True, path)`` or ``(False, reason)``; never raises."""

    try:
        return True, resolve_ffmpeg()
    except AudioUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # health checks must never crash the caller
        logger.warning("ffmpeg availability check failed: %s", exc)
        return False, f"ffmpeg availability check failed: {exc}"


def reset_cache() -> None:
    """Clear the cached executable (tests and post-install refreshes)."""

    global _cached_path
    _cached_path = None


__all__ = [
    "AudioUnavailable",
    "ffmpeg_available",
    "reset_cache",
    "resolve_ffmpeg",
]
