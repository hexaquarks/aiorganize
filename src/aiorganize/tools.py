from typing import TYPE_CHECKING

from langchain.tools import BaseTool, tool

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


async def _chrome_tab_id(context: "BrowserContext", page: "Page") -> str:
    session = await context.new_cdp_session(page)
    try:
        target = await session.send("Target.getTargetInfo")
        # These are debugging target IDs, not Chrome extension tab IDs.
        return target["targetInfo"]["targetId"]
    finally:
        await session.detach()


def chrome_tab_tool(context: "BrowserContext") -> BaseTool:
    """Build a read-only tool scoped to the test browser context."""

    @tool("list_tabs")
    async def list_chrome_tabs() -> list[dict[str, str]]:
        """List the live browser tabs with their IDs, titles, and URLs."""
        tabs = []
        for page in context.pages:
            tabs.append(
                {
                    "id": await _chrome_tab_id(context, page),
                    "title": await page.title(),
                    "url": page.url,
                }
            )

        return tabs

    return list_chrome_tabs


def chrome_read_tab_tool(context: "BrowserContext") -> BaseTool:
    """Build a page-reading tool scoped to the same isolated test browser."""

    @tool("read_tab")
    async def read_chrome_tab(tab_id: str) -> dict[str, str]:
        """Read up to 4,000 characters of visible page text for an existing tab ID."""
        for page in context.pages:
            if await _chrome_tab_id(context, page) == tab_id:
                content = await page.locator("body").inner_text(timeout=5_000)
                return {"id": tab_id, "content": content[:4_000]}
        return {"id": tab_id, "error": "Tab not found."}

    return read_chrome_tab
