"""Render store artwork and an actual panel preview using offline sample tabs."""

import asyncio
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, expect

from aiorganize.chrome_groups import GROUP_BROWSER_ARGS, load_group_extension
from demos.fixtures import EXTENSION_PATH, create_test_tabs


STORE = Path(__file__).resolve().parents[1] / "store"
ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect x="16" y="16" width="96" height="96" rx="24" fill="#6558e8"/>
  <rect x="33" y="38" width="27" height="52" rx="7" fill="#ffffff"/>
  <rect x="68" y="38" width="27" height="23" rx="7" fill="#d5d0ff"/>
  <rect x="68" y="69" width="27" height="21" rx="7" fill="#a7ead7"/>
</svg>"""


async def main() -> None:
    icons = EXTENSION_PATH / "icons"
    icons.mkdir(exist_ok=True)
    STORE.mkdir(exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = await browser.new_page(device_scale_factor=1)
            for size in (16, 32, 48, 128):
                await page.set_viewport_size({"width": size, "height": size})
                await page.set_content('<style>body{margin:0;background:transparent}</style>' + ICON)
                await page.screenshot(path=str(icons / f"{size}.png"), omit_background=True)

            await page.set_viewport_size({"width": 440, "height": 280})
            await page.set_content('''<style>
                body{margin:0;background:#25204f;display:grid;place-items:center;height:100vh}
                svg{width:240px;height:240px}
                </style>''' + ICON)
            await page.screenshot(path=str(STORE / "promo-440x280.png"))
        finally:
            await browser.close()

        with tempfile.TemporaryDirectory(prefix="aiorganize-store-") as profile:
            context = await playwright.chromium.launch_persistent_context(
                profile, channel="chrome", headless=True, args=GROUP_BROWSER_ARGS,
                ignore_default_args=["--disable-extensions"],
                viewport={"width": 1280, "height": 800}, device_scale_factor=1, color_scheme="light",
            )
            try:
                worker = await load_group_extension(context, EXTENSION_PATH)
                await create_test_tabs(context)
                panel = await context.new_page()
                await panel.goto(worker.url.removesuffix("background.js") + "panel.html")
                # Use the real UI with a deterministic proposal; no API call or personal tabs are captured.
                await panel.evaluate("""async () => {
                    const {panel} = await import('./panel-entry.js');
                    const {mountPanel} = await import('./panel.js');
                    panel.destroy();
                    mountPanel(document, async ({snapshot}) => ({groups: [
                        {name: 'Dev', tab_ids: snapshot.slice(0, 2).map(tab => tab.id)},
                        {name: 'Cooking', tab_ids: [snapshot[2].id, snapshot[4].id]},
                        {name: 'Travel', tab_ids: [snapshot[3].id, snapshot[5].id]},
                    ]}));
                }""")
                await panel.get_by_role("button", name="Organize tabs", exact=True).click()
                await expect(panel.locator("#preview")).to_be_visible()
                await panel.screenshot(path=str(STORE / "preview-1280x800.png"))
            finally:
                await context.close()


if __name__ == "__main__":
    asyncio.run(main())
