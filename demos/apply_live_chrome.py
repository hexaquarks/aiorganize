import argparse
import asyncio
import os
from urllib.parse import urlparse

from playwright.async_api import Error, async_playwright

from aiorganize.chrome_groups import open_group_control_page
from demos.apply_chrome import review_and_apply
from demos.chrome_session import DEBUG_ENDPOINT, ensure_debug_chrome
from demos.fixtures import EXTENSION_PATH


async def run_live(endpoint: str) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in .env, then run make run.")

    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "ws"} or parsed.hostname not in {
        "localhost", "127.0.0.1", "::1"
    }:
        raise SystemExit("The Chrome debugging endpoint must be local (localhost or 127.0.0.1).")

    if endpoint == DEBUG_ENDPOINT:
        print(ensure_debug_chrome(), flush=True)

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.connect_over_cdp(endpoint, no_defaults=True)
        except Error as error:
            raise SystemExit(f"Could not connect to Chrome at {endpoint}: {error}") from error

        try:
            if len(browser.contexts) != 1:
                raise RuntimeError("Expected one Chrome profile on the debugging endpoint.")
            context = browser.contexts[0]
            if not context.pages:
                # Chrome can keep its debugging port open after the last window closes.
                await context.new_page()
                print("Opened the AI Organize Chrome window.", flush=True)
            control_page = await open_group_control_page(context, EXTENSION_PATH)
            try:
                window_id = await control_page.evaluate("() => activeWindowId()")
                print(f"Using Chrome window {window_id} on {endpoint}.")
                await review_and_apply(context, control_page, window_id=window_id)
            finally:
                await control_page.close()
        except EOFError:
            print("\nInput ended. No further changes were made.")
        finally:
            # A CDP connection is detached without closing the user's running Chrome.
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Review and apply groups in the last focused Chrome window.",
        epilog=(
            "Starts or reuses the dedicated Chrome session and loads the local grouping extension. "
            "If the session is new, open your tabs there when prompted."
        ),
    )
    parser.add_argument("--endpoint", default=DEBUG_ENDPOINT)
    arguments = parser.parse_args()
    asyncio.run(run_live(arguments.endpoint))
