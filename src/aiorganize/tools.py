from typing import TYPE_CHECKING

from langchain.tools import BaseTool, tool
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Worker


async def _chrome_tab_id(context: "BrowserContext", page: "Page") -> str:
    session = await context.new_cdp_session(page)
    try:
        target = await session.send("Target.getTargetInfo")
        # These are debugging target IDs, not Chrome extension tab IDs.
        return target["targetInfo"]["targetId"]
    finally:
        await session.detach()


async def _tab_pages(
    context: "BrowserContext", worker: "Worker | Page | None", window_id: int | None
) -> list[tuple[str, "Page"]]:
    target_ids = None
    if worker is not None:
        state = await worker.evaluate("() => tabGroupState()")
        target_ids = {tab["id"] for tab in state["tabs"] if tab["window_id"] == window_id}

    pages = []
    for page in context.pages:
        tab_id = await _chrome_tab_id(context, page)
        if target_ids is None or tab_id in target_ids:
            pages.append((tab_id, page))
    return pages


def chrome_tab_tool(
    context: "BrowserContext", *, worker: "Worker | Page | None" = None,
    window_id: int | None = None,
) -> BaseTool:
    """Build a read-only tool for a browser context or one selected window."""

    if (worker is None) != (window_id is None):
        raise ValueError("worker and window_id must be provided together.")

    @tool("list_tabs")
    async def list_chrome_tabs() -> list[dict[str, str]]:
        """List the live browser tabs with their IDs, titles, and URLs."""
        if worker is not None:
            state = await worker.evaluate("() => tabGroupState()")
            return [
                {"id": tab["id"], "title": tab["title"], "url": tab["url"]}
                for tab in state["tabs"]
                if tab["window_id"] == window_id
            ]

        tabs = []
        for tab_id, page in await _tab_pages(context, None, None):
            tabs.append(
                {
                    "id": tab_id,
                    "title": await page.title(),
                    "url": page.url,
                }
            )

        return tabs

    return list_chrome_tabs


def chrome_read_tab_tool(
    context: "BrowserContext", *, worker: "Worker | Page | None" = None,
    window_id: int | None = None,
) -> BaseTool:
    """Build a page-reading tool scoped to the same context or selected window."""

    if (worker is None) != (window_id is None):
        raise ValueError("worker and window_id must be provided together.")

    @tool("read_tab")
    async def read_chrome_tab(tab_id: str) -> dict[str, str]:
        """Read up to 4,000 characters of visible page text for an existing tab ID."""
        unavailable = {
            "id": tab_id,
            "content": "",
            "note": "Page text is unavailable. Use the tab title and URL to group it.",
        }
        for current_id, page in await _tab_pages(context, worker, window_id):
            if current_id == tab_id:
                if not page.url:
                    return unavailable
                try:
                    content = await page.locator("body").inner_text(timeout=5_000)
                except PlaywrightTimeoutError:
                    return unavailable
                return {"id": tab_id, "content": content[:4_000]}

        if worker is not None:
            state = await worker.evaluate("() => tabGroupState()")
            if any(
                tab["id"] == tab_id and tab["window_id"] == window_id
                for tab in state["tabs"]
            ):
                return unavailable
        return {"id": tab_id, "error": "Tab not found."}

    return read_chrome_tab
