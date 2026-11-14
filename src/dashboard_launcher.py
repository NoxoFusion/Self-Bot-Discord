"""Start and stop the local dashboard backend and web frontend.

The bot launcher can optionally bring up the dashboard alongside the bot.  The
backend prints a six-digit pairing code on startup; this module captures it from
the backend log so the launcher can show it to the user.  Every helper is
best-effort: a busy port, a missing npm, or a crashed child must never prevent
the bot itself from starting.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8765
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 4000

PAIRING_CODE_RE = re.compile(r"Pairing code:\s*(\d{6})")


@dataclass
class DashboardHandles:
    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    pairing_code: str | None = None
    backend_log: Path | None = None
    web_url: str = "http://127.0.0.1:4000"


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return ``True`` when a TCP connection to ``host:port`` succeeds."""

    try:
        connection = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    try:
        connection.close()
    except OSError:
        pass
    return True


def extract_pairing_code(text: str) -> str | None:
    """Return the six-digit pairing code found in ``text``, if any."""

    match = PAIRING_CODE_RE.search(text)
    return match.group(1) if match is not None else None


def wait_for_pairing_code(
    log_path: str | Path,
    timeout: float = 15.0,
    interval: float = 0.2,
) -> str | None:
    """Poll ``log_path`` until a pairing code appears or ``timeout`` expires."""

    path = Path(log_path)
    deadline = time.monotonic() + timeout
    while True:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        code = extract_pairing_code(text)
        if code is not None:
            return code
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def wait_for_port(
    host: str,
    port: int,
    timeout: float = 40.0,
    interval: float = 0.5,
) -> bool:
    """Wait until ``host:port`` accepts connections, or ``timeout`` expires."""

    deadline = time.monotonic() + timeout
    while True:
        if is_port_open(host, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def start_backend(
    repo_root: Path,
    host: str = DEFAULT_BACKEND_HOST,
    port: int = DEFAULT_BACKEND_PORT,
) -> tuple[subprocess.Popen | None, str | None, Path]:
    """Start the dashboard API backend and capture its pairing code.

    Returns ``(process, pairing_code, log_path)``.  When the port is already
    open the backend is assumed to be running and ``(None, None, log_path)`` is
    returned.
    """

    repo_root = Path(repo_root)
    log_path = repo_root / "data" / "dashboard_backend.out"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if is_port_open(host, port):
        return None, None, log_path

    backend_script = repo_root / "dashboard" / "backend" / "main.py"
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(backend_script)],
            cwd=str(repo_root),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    pairing_code = wait_for_pairing_code(log_path)
    return process, pairing_code, log_path


def start_frontend(
    web_dir: Path,
    host: str = DEFAULT_WEB_HOST,
    port: int = DEFAULT_WEB_PORT,
) -> subprocess.Popen | None:
    """Start the dashboard web frontend, or return ``None`` if already up."""

    web_dir = Path(web_dir)
    if is_port_open(host, port):
        return None

    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    process = subprocess.Popen(
        [npm, "run", "dev", "--", "--host", host, "--port", str(port)],
        cwd=str(web_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    wait_for_port(host, port, timeout=40)
    return process


def _stop_process(process: subprocess.Popen | None) -> None:
    """Terminate one child process, ignoring every error."""

    if process is None:
        return

    try:
        if process.poll() is not None:
            return
    except Exception:
        return

    if sys.platform == "win32":
        # npm.cmd spawns node; /T kills the whole tree so the port is freed.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
            )
        except Exception:
            pass
        return

    try:
        process.terminate()
    except Exception:
        return

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return

    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def stop_handles(handles: DashboardHandles) -> None:
    """Stop the frontend and backend children, best-effort and never raising."""

    _stop_process(handles.frontend)
    _stop_process(handles.backend)


def ask_open_dashboard(argv: list[str], stdin=None) -> bool:
    """Decide whether the launcher should start the dashboard.

    ``--dashboard`` and ``--no-dashboard`` win over the interactive prompt.
    Non-interactive stdin always answers no so a background launch never hangs.
    """

    if "--dashboard" in argv:
        return True
    if "--no-dashboard" in argv:
        return False

    if stdin is None:
        stdin = sys.stdin

    try:
        if not stdin.isatty():
            return False
    except (AttributeError, OSError, ValueError):
        return False

    prompt = "Mở dashboard kèm mã kích hoạt? [Y/n]: "
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        answer = stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return False
    except (AttributeError, OSError, ValueError):
        return False

    if answer == "":
        return False

    answer = answer.strip().lower()
    if answer in {"n", "no", "0"}:
        return False
    return True


def start_dashboard(
    repo_root: Path,
    web_dir: Path,
    open_browser: bool = True,
) -> DashboardHandles:
    """Start the dashboard backend and frontend, returning their handles.

    This function never raises: a failure in either child leaves the
    corresponding handle as ``None`` and the bot keeps running.
    """

    handles = DashboardHandles()

    try:
        backend, pairing_code, log_path = start_backend(repo_root)
        handles.backend = backend
        handles.pairing_code = pairing_code
        handles.backend_log = log_path
    except Exception:
        pass

    try:
        handles.frontend = start_frontend(web_dir)
    except Exception:
        pass

    try:
        frontend_up = is_port_open(DEFAULT_WEB_HOST, DEFAULT_WEB_PORT)
    except Exception:
        frontend_up = False

    if frontend_up and open_browser:
        try:
            webbrowser.open(handles.web_url)
        except Exception:
            pass

    return handles
