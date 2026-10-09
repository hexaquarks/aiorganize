from typing import TYPE_CHECKING

from langchain.tools import BaseTool, tool

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


@tool
def list_tabs() -> list[dict[str, int | str]]:
    """List three fake browser tabs with their IDs, titles, and URLs."""
    return [
        {"id": 1, "title": "Python Tutorial", "url": "https://docs.python.org/3/tutorial/"},
        {"id": 2, "title": "LangChain Docs", "url": "https://docs.langchain.com/"},
        {"id": 3, "title": "ChatGPT", "url": "https://chatgpt.com/"},
    ]


@tool
def read_tab(tab_id: int) -> dict[str, int | str]:
    """Read the text of a fake tab by its ID to understand its topic."""
    content = {
        1: "Learn Python functions, loops, and classes.",
        2: "Build Python agents using LangChain tools and chat models.",
        3: "A conversation about making fresh pasta and tomato sauce.",
    }
    if tab_id not in content:
        return {"id": tab_id, "error": "Tab not found."}
    return {"id": tab_id, "content": content[tab_id]}


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
