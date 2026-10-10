import os
import plistlib
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


DEBUG_PORT = 9222
DEBUG_ENDPOINT = f"http://127.0.0.1:{DEBUG_PORT}"
PROFILE_PATH = Path.home() / "Library/Application Support/AI Organize Chrome"


def _port_is_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", DEBUG_PORT), timeout=1):
            return True
    except OSError:
        return False


def _debug_endpoint_responds() -> bool:
    try:
        with urlopen(f"{DEBUG_ENDPOINT}/json/version", timeout=2) as response:
            return b'"webSocketDebuggerUrl"' in response.read()
    except (OSError, URLError):
        return False


def _profile_chrome_pids() -> set[int]:
    processes = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout
    profile_flag = f"--user-data-dir={PROFILE_PATH}"
    return {
        int(line.strip().split(None, 1)[0])
        for line in processes.splitlines()
        if profile_flag in line and "/Google Chrome.app/Contents/MacOS/Google Chrome " in line
    }


def _port_owner_pids() -> set[int]:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{DEBUG_PORT}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"Could not inspect port {DEBUG_PORT}: {result.stderr.strip()}")
    return {int(line) for line in result.stdout.splitlines()}


def _chrome_app() -> Path:
    candidates = [Path.home() / "Desktop/Google Chrome.app", Path("/Applications/Google Chrome.app")]
    installed = []
    for app in candidates:
        info_path = app / "Contents/Info.plist"
        if not info_path.is_file():
            continue
        with info_path.open("rb") as info_file:
            version = plistlib.load(info_file).get("CFBundleShortVersionString", "0")
        installed.append((tuple(int(part) for part in version.split(".") if part.isdigit()), app))
    if not installed:
        raise RuntimeError("Google Chrome was not found in Applications or Desktop.")
    return max(installed)[1]


def ensure_debug_chrome() -> str:
    """Reuse the project profile or restart only its stale Chrome process."""
    profile_pids = _profile_chrome_pids()
    if _port_is_open():
        owner_pids = _port_owner_pids()
        if not owner_pids or not owner_pids <= profile_pids:
            raise RuntimeError(f"Port {DEBUG_PORT} belongs to another process; it was left untouched.")
        if _debug_endpoint_responds():
            return "Reusing the AI Organize Chrome session."
    else:
        owner_pids = set()

    stale_pids = owner_pids or profile_pids
    for pid in stale_pids:
        os.kill(pid, signal.SIGTERM)

    for _ in range(50):
        if not _port_is_open() and not (_profile_chrome_pids() & stale_pids):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("The stale AI Organize Chrome process did not close. Its port was left unchanged.")

    PROFILE_PATH.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "open", "-na", str(_chrome_app()), "--args",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={PROFILE_PATH}",
            "--no-first-run", "--no-default-browser-check", "about:blank",
        ],
        check=True,
    )
    for _ in range(100):
        if _debug_endpoint_responds():
            return "Started AI Organize Chrome on port 9222."
        time.sleep(0.1)
    raise RuntimeError("Chrome started, but its debugging port did not become ready.")
