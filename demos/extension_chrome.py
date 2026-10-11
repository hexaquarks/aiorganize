import asyncio
import os
from pathlib import Path

from playwright.async_api import BrowserContext, Error, async_playwright

from aiorganize.chrome_groups import open_group_control_page
from aiorganize.install_companion import install_companion
from demos.chrome_session import DEBUG_ENDPOINT, PROFILE_PATH, ensure_debug_chrome
from demos.fixtures import EXTENSION_PATH


async def prepare_extension(context: BrowserContext, profile: Path) -> Path:
    """Load the extension and register its companion in the same Chrome profile."""
    if not context.pages:
        await context.new_page()
    control_page = await open_group_control_page(context, EXTENSION_PATH)
    try:
        extension_id = await control_page.evaluate("() => chrome.runtime.id")
        await control_page.evaluate("() => chrome.storage.local.set({developmentCompanion: true})")
        project = EXTENSION_PATH.parent
        return install_companion(extension_id, project, profile / "NativeMessagingHosts")
    finally:
        await control_page.close()


async def run_extension() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in .env, then run make run.")
    print(ensure_debug_chrome(), flush=True)
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.connect_over_cdp(DEBUG_ENDPOINT, no_defaults=True)
        except Error as error:
            raise SystemExit("Could not connect to AI Organize Chrome. Run make run again.") from error
        try:
            if len(browser.contexts) != 1:
                raise RuntimeError("Expected one Chrome profile in the AI Organize session.")
            manifest = await prepare_extension(browser.contexts[0], PROFILE_PATH)
            print(f"Registered Python companion: {manifest}")
            print("Ready. Open your tabs, click the AI Organize extension, then click Organize tabs.")
            print("Review and approve groups in the side panel. No terminal input is needed.")
        except Error as error:
            raise SystemExit("Chrome closed during setup. Run make run again and leave its window open.") from error
        finally:
            # Setup is finished; detach while leaving Chrome and its tabs open.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_extension())
