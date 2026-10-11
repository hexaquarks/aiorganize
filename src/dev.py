"""Open Chrome with the source extension: python -m src.dev."""

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Error, async_playwright


EXTENSION_PATH = Path(__file__).resolve().parents[1] / "extension"
CHROME_ARGS = ["--enable-unsafe-extension-debugging"]
DEFAULT_PROFILE = Path.home() / ".aiorganize" / "chrome"


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
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="Dedicated development Chrome profile.")
    parser.add_argument("--check", action="store_true", help="Check startup headlessly, then exit without an API call.")
    args = parser.parse_args()
    try:
        asyncio.run(run_dev(args.profile.resolve(), check=args.check))
    except KeyboardInterrupt:
        pass
    except Error as error:
        raise SystemExit(
            f"Could not start development Chrome. Close any Chrome using this profile and retry. {error}"
        ) from None


if __name__ == "__main__":
    main()
