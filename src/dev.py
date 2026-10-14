"""Local Chrome development helpers."""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Error, async_playwright

from .build import PROJECT, build_frontend

EXTENSION_PATH = PROJECT / "extension"
CHROME_ARGS = ["--enable-unsafe-extension-debugging"]
DEFAULT_PROFILE = Path.home() / ".aiorganize" / "chrome"
# Playwright uses zero to disable the deadline while the developer keeps Chrome open.
NO_BROWSER_CLOSE_TIMEOUT = 0


def _macos_chrome() -> tuple[list[Path], Path, str]:
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    profile = Path.home() / "Library/Application Support/Google/Chrome"

    return candidates, profile, "open"


def _windows_chrome() -> tuple[list[Path], Path, str]:
    candidates = []

    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(name)
        if root:
            candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")

    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    profile = local_app_data / "Google/Chrome/User Data"

    return candidates, profile, "explorer.exe"


def _linux_chrome() -> tuple[list[Path], Path, str]:
    candidates = []

    for name in ("google-chrome", "google-chrome-stable"):
        executable = shutil.which(name)
        if executable:
            candidates.append(Path(executable))

    config = os.environ.get("CHROME_CONFIG_HOME") or os.environ.get("XDG_CONFIG_HOME")
    config_dir = Path(config) if config else Path.home() / ".config"
    profile = Path(os.environ.get("CHROME_USER_DATA_DIR") or config_dir / "google-chrome")

    return candidates, profile, "xdg-open"


def _chrome_setup() -> tuple[list[Path], Path, str]:
    if sys.platform == "darwin":
        return _macos_chrome()

    if sys.platform == "win32":
        return _windows_chrome()

    if sys.platform.startswith("linux"):
        return _linux_chrome()

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _open_source_folder(command: str) -> None:
    opener = shutil.which(command)

    if opener:
        subprocess.Popen([opener, str(EXTENSION_PATH)])
    else:
        print(EXTENSION_PATH)


def open_regular_chrome() -> None:
    """Open the extension manager and source folder using the local Chrome installation."""
    candidates, profile, folder_opener = _chrome_setup()
    chrome = next((path for path in candidates if path.is_file()), None)

    if chrome is None:
        raise RuntimeError("Chrome not found.")

    # Explicitly target the normal data directory, even while isolated dev Chrome is running.
    subprocess.Popen(
        [str(chrome), f"--user-data-dir={profile}", "chrome://extensions/"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _open_source_folder(folder_opener)


async def load_extension(context: BrowserContext, extension_path: Path = EXTENSION_PATH) -> str:
    """Load source files into the development/test browser without a build."""
    if context.browser is None:
        raise RuntimeError("A Playwright-managed browser is required.")

    session = await context.browser.new_browser_cdp_session()

    try:
        # Current Chrome uses this debugging API instead of --load-extension.
        result = await session.send("Extensions.loadUnpacked", {"path": str(extension_path.resolve())})
        return result["id"]
    finally:
        await session.detach()


async def run_dev(profile: Path, *, check: bool = False) -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=check,
            args=CHROME_ARGS,
            ignore_default_args=["--disable-extensions"],
        )

        try:
            extension_id = await load_extension(context)
            panel = await context.new_page()
            await panel.goto(f"chrome-extension://{extension_id}/panel.html")
            await panel.wait_for_function("document.querySelector('#approve')?.disabled === true")

            if check:
                return

            await context.wait_for_event("close", timeout=NO_BROWSER_CLOSE_TIMEOUT)
        finally:
            await context.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        build_frontend(development=True)

        if args.isolated or args.check or args.profile:
            profile = (args.profile or DEFAULT_PROFILE).resolve()
            asyncio.run(run_dev(profile, check=args.check))
        else:
            open_regular_chrome()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, Error) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
