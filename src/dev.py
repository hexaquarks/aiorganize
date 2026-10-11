"""Open Chrome with the source extension: python -m src.dev."""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Error, async_playwright


EXTENSION_PATH = Path(__file__).resolve().parents[1] / "extension"
CHROME_ARGS = ["--enable-unsafe-extension-debugging"]
DEFAULT_PROFILE = Path.home() / ".aiorganize" / "chrome"


def open_regular_chrome() -> None:
    """Open the extension manager without automating or replacing the user's Chrome profile."""
    if sys.platform != "darwin":
        raise RuntimeError("Open chrome://extensions in Chrome and load the extension/ folder, or use --isolated.")

    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not chrome.is_file():
        chrome = Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not chrome.is_file():
        raise RuntimeError("Google Chrome was not found. Open chrome://extensions manually.")

    # Explicitly target the normal data directory, even while isolated dev Chrome is running.
    profile = Path.home() / "Library/Application Support/Google/Chrome"
    subprocess.Popen(
        [str(chrome), f"--user-data-dir={profile}", "chrome://extensions/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(["open", str(EXTENSION_PATH)], check=True)
    print("Opened your usual Chrome. One-time setup:", flush=True)
    print("Enable Developer mode, click Load unpacked, and select:", flush=True)
    print(EXTENSION_PATH, flush=True)
    print("Then click the AI Organize toolbar icon. Reload the extension here after editing.", flush=True)


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
            str(profile), channel="chrome", headless=check, args=CHROME_ARGS,
            ignore_default_args=["--disable-extensions"],
        )
        try:
            extension_id = await load_extension(context)
            panel = await context.new_page()
            await panel.goto(f"chrome-extension://{extension_id}/panel.html")
            await panel.wait_for_function("document.querySelector('#approve')?.disabled === true")
            print(f"Loaded source extension: {EXTENSION_PATH}", flush=True)
            if check:
                print("Development startup check passed; no model request was made.", flush=True)
                return
            print("Add your API key in API settings. Open tabs and use the extension's side panel.", flush=True)
            print(
                "Reload the extension at chrome://extensions after editing. Close Chrome or press Ctrl+C to stop.",
                flush=True,
            )
            await context.wait_for_event("close", timeout=0)
        finally:
            await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open development Chrome with the source extension.")
    parser.add_argument("--isolated", action="store_true", help="Launch an automated Chrome with a separate profile.")
    parser.add_argument("--profile", type=Path, help="Use this isolated development profile instead of the default.")
    parser.add_argument("--check", action="store_true", help="Check startup headlessly, then exit without an API call.")
    args = parser.parse_args()
    try:
        if args.isolated or args.check or args.profile:
            asyncio.run(run_dev((args.profile or DEFAULT_PROFILE).resolve(), check=args.check))
        else:
            open_regular_chrome()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
    except Error as error:
        raise SystemExit(
            f"Could not start development Chrome. Close any Chrome using this profile and retry. {error}"
        ) from None


if __name__ == "__main__":
    main()
