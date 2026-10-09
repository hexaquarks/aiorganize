from typing import TYPE_CHECKING

from langchain.tools import BaseTool, tool

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext


@tool
def list_tabs() -> list[dict[str, int | str]]:
    """List three fake browser tabs with their IDs, titles, and URLs."""
    return [
        {"id": 1, "title": "Python Tutorial", "url": "https://docs.python.org/3/tutorial/"},
        {"id": 2, "title": "LangChain Docs", "url": "https://docs.langchain.com/"},
        {"id": 3, "title": "Wikipedia", "url": "https://en.wikipedia.org/"},
    ]


def chrome_tab_tool(context: "BrowserContext") -> BaseTool:
    """Build a read-only tool scoped to the test browser context."""

    @tool("list_tabs")
    async def list_chrome_tabs() -> list[dict[str, str]]:
        """List the live browser tabs with their IDs, titles, and URLs."""
        tabs = []
        for page in context.pages:
            session = await context.new_cdp_session(page)
            try:
                target = await session.send("Target.getTargetInfo")
                tabs.append(
                    {
                        # These are debugging target IDs, not Chrome extension tab IDs.
                        "id": target["targetInfo"]["targetId"],
                        "title": await page.title(),
                        "url": page.url,
                    }
                )
            finally:
                await session.detach()

        return tabs

    return list_chrome_tabs
