"""Render store artwork and an actual panel preview using offline sample tabs."""

import asyncio
import base64
import json
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, expect

from src.dev import CHROME_ARGS, load_extension
from tests.fixtures import EXTENSION_PATH, create_test_tabs


STORE = Path(__file__).resolve().parents[1] / "store"


async def main() -> None:
    STORE.mkdir(exist_ok=True)
    icon = base64.b64encode((EXTENSION_PATH / "icons/brand.png").read_bytes()).decode()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = await browser.new_page(device_scale_factor=1)
            await page.set_viewport_size({"width": 440, "height": 280})
            await page.set_content(f"""<style>
                body{{margin:0;background:#25204f;display:grid;place-items:center;height:100vh}}
                img{{width:240px;height:240px;object-fit:contain}}
                </style><img src="data:image/png;base64,{icon}" alt="">""")
            await page.locator("img").evaluate("image => image.decode()")
            await page.screenshot(path=str(STORE / "promo-440x280.png"))
        finally:
            await browser.close()

        with tempfile.TemporaryDirectory(prefix="aiorganize-store-") as profile:
            context = await playwright.chromium.launch_persistent_context(
                profile,
                channel="chrome",
                headless=True,
                args=CHROME_ARGS,
                ignore_default_args=["--disable-extensions"],
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
                color_scheme="light",
                reduced_motion="reduce",
            )
            try:
                extension_id = await load_extension(context, EXTENSION_PATH)
                await create_test_tabs(context)
                panel = await context.new_page()
                # Exercise the real connection and grouping UI with offline API responses.
                await panel.route(
                    "https://api.openai.com/v1/models",
                    lambda route: route.fulfill(
                        json={
                            "data": [],
                        }
                    ),
                )

                async def respond(route):
                    tabs = json.loads(route.request.post_data_json["input"])["tabs"]
                    categories = {
                        "Python Tutorial": "Dev",
                        "LangChain Docs": "Dev",
                        "ChatGPT": "AI",
                        "Pasta Recipes": "Cooking",
                        "Toronto Travel Guide": "Travel",
                    }
                    groups = {}
                    for tab in tabs:
                        category = categories.get(tab["title"], "Other")
                        groups.setdefault(category, []).append(tab["id"])
                    proposal = {"groups": [{"name": name, "tab_ids": ids} for name, ids in groups.items()]}
                    await route.fulfill(
                        json={
                            "status": "completed",
                            "output": [
                                {
                                    "content": [
                                        {
                                            "type": "output_text",
                                            "text": json.dumps(proposal),
                                        }
                                    ]
                                }
                            ],
                        }
                    )

                await panel.route("https://api.openai.com/v1/responses", respond)
                await panel.goto(f"chrome-extension://{extension_id}/panel.html")
                await panel.locator("#api-key").fill("offline-preview-key")
                await panel.locator("#test-connection").click()
                await expect(panel.locator("#ready")).to_be_visible()
                await panel.locator("#organize").click()
                await expect(panel.locator("#preview")).to_be_visible()
                await panel.screenshot(path=str(STORE / "preview-1280x800.png"))
            finally:
                await context.close()


if __name__ == "__main__":
    asyncio.run(main())
