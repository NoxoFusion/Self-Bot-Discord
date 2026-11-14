"""Cross-process single-instance lock for the bot.

A second ``python main.py`` must not start while the first is alive: two gateway
sessions with the same user token can make Discord invalidate the session
(close 4003/4004).  The lock is an OS-level file lock, released automatically
when the owning process exits, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# After killing an old bot, give Discord time to close its gateway session
# before the new process logs in. Immediate re-login can look like account
# takeover and trigger a forced password reset.
KILL_SETTLE_SECONDS = 15.0

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

_held_handle = None


def acquire_single_instance_lock(path: str | Path):
    """Try to take the exclusive lock.

    Returns the open handle on success, or ``None`` when another process owns
    the lock.  Keep the returned handle alive for the process lifetime.
    """

    global _held_handle

    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - no locking primitive available
            handle.close()
            return None
    except OSError:
        handle.close()
        return None

    _held_handle = handle
    return handle


def release_single_instance_lock() -> None:
    """Release the lock (also released automatically when the process exits)."""

    global _held_handle
    handle = _held_handle
    _held_handle = None
    if handle is None:
        return
    try:
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


def write_pid_file(path: str | Path) -> None:
    """Atomically write the current process PID to ``path``."""

    pid_path = Path(path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{pid_path.name}.", suffix=".tmp", dir=str(pid_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, pid_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def read_pid_file(path: str | Path) -> int | None:
    """Read a PID from ``path``; return ``None`` when missing or invalid."""

    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not raw:
        return None
    try:
        pid = int(raw.splitlines()[0].strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _list_processes() -> list[tuple[int, str]]:
    """Return ``(pid, command_line)`` pairs for every visible process."""

    try:
        if sys.platform == "win32":
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if completed.returncode != 0 or not completed.stdout.strip():
                return []
            data = json.loads(completed.stdout)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                return []
            processes: list[tuple[int, str]] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                pid = item.get("ProcessId")
                if not isinstance(pid, int):
                    continue
                processes.append((pid, str(item.get("CommandLine") or "")))
            return processes

        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            return []
        processes = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            processes.append((pid, parts[1] if len(parts) > 1 else ""))
        return processes
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def find_bot_pids(exclude_pid: int | None = None) -> list[int]:
    """Find running bot processes that are safe to terminate."""

    current_pid = os.getpid()
    found: set[int] = set()

    for pid, command_line in _list_processes():
        command = (command_line or "").lower()
        if "main.py" not in command:
            continue
        # Only the dashboard backend is a separate app; the bot's own
        # --dashboard / --no-dashboard flags must not exclude it.
        if re.search(r"dashboard[/\\]backend[/\\]main\.py", command):
            continue
        if "single_instance" in command:
            continue
        if pid == current_pid or (exclude_pid is not None and pid == exclude_pid):
            continue

        if sys.platform == "win32":
            if "powershell" in command or "pwsh" in command:
                continue
            if "python.exe" not in command and "py.exe" not in command:
                continue
        else:
            first_token = command.split(maxsplit=1)[0] if command.split() else ""
            if "python" not in first_token:
                continue

        found.add(pid)

    return sorted(found)


def is_pid_alive(pid: int) -> bool:
    """Return ``True`` when ``pid`` refers to a live process."""

    if pid <= 0:
        return False

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

            process_handle = kernel32.OpenProcess(
                0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
                False,
                pid,
            )
            if not process_handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(
                    process_handle, ctypes.byref(exit_code)
                ):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(process_handle)
        except (OSError, AttributeError):
            return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def kill_bot_processes(pids: list[int]) -> list[int]:
    """Terminate ``pids`` and return the ones confirmed dead."""

    killed: list[int] = []
    current_pid = os.getpid()

    for pid in pids:
        if pid == current_pid:
            continue
        try:
            os.kill(pid, 9 if sys.platform == "win32" else signal.SIGTERM)
        except OSError:
            continue

        deadline = time.monotonic() + 5.0
        dead = False
        while True:
            dead = not is_pid_alive(pid)
            if dead or time.monotonic() >= deadline:
                break
            time.sleep(0.2)

        if dead:
            killed.append(pid)

    return killed


def acquire_with_cleanup(
    lock_path: str | Path,
    pid_path: str | Path,
    timeout: float = 10.0,
) -> tuple[object | None, list[int]]:
    """Acquire the single-instance lock, killing stale bot processes first.

    Returns ``(handle, killed_pids)``.  ``handle`` is ``None`` when the lock
    could not be acquired within ``timeout`` seconds.
    """

    handle = acquire_single_instance_lock(lock_path)
    if handle is not None:
        write_pid_file(pid_path)
        return handle, []

    pids = find_bot_pids()
    killed = kill_bot_processes(pids)
    if killed:
        # Cho Discord đóng session cũ hẳn trước khi login session mới —
        # login lại quá sát nhau dễ bị coi là chiếm đoạt tài khoản.
        logger.warning(
            "Stopped old bot instance(s) %s — waiting %.0fs for Discord "
            "to close the old session",
            killed,
            KILL_SETTLE_SECONDS,
        )
        time.sleep(KILL_SETTLE_SECONDS)

    deadline = time.monotonic() + timeout
    while True:
        handle = acquire_single_instance_lock(lock_path)
        if handle is not None:
            write_pid_file(pid_path)
            return handle, killed
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, killed
        time.sleep(min(0.5, remaining))
