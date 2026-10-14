import json
from html import escape

from playwright.async_api import BrowserContext, Route

from src.build import COMPILED_EXTENSION as EXTENSION_PATH

TEST_TABS = {
    "https://tabs.test/python": "Python Tutorial",
    "https://tabs.test/langchain": "LangChain Docs",
    "https://tabs.test/chat": "ChatGPT",
    "https://tabs.test/new": "New Tab",
    "https://tabs.test/recipes": "Pasta Recipes",
    "https://tabs.test/travel": "Toronto Travel Guide",
}

PRIVATE_PAGE_TEXT = "Private page contents must never be sent to the model."


async def create_test_tabs(context: BrowserContext) -> None:
    async def serve(route: Route) -> None:
        # Offline pages have real-looking URLs and private text to detect accidental page reads.
        title = escape(TEST_TABS[route.request.url])
        await route.fulfill(
            content_type="text/html",
            body=f"<!doctype html><title>{title}</title><h1>{title}</h1><p>{PRIVATE_PAGE_TEXT}</p>",
        )

    await context.route("https://tabs.test/**", serve)

    # Chrome starts with a blank tab; use it for the first test page.
    first_page = context.pages[0] if context.pages else await context.new_page()

    for index, url in enumerate(TEST_TABS):
        page = first_page if index == 0 else await context.new_page()
        await page.goto(url)


TAB_STATE = """async () => {
    const tabs = (await chrome.tabs.query({})).filter(tab => !tab.url?.startsWith(chrome.runtime.getURL('')));
    const groups = await chrome.tabGroups.query({});
    return {
        tabs: tabs.map(tab => ({id: `tab-${tab.id}`, chrome_id: tab.id, group_id: tab.groupId,
            window_id: tab.windowId, index: tab.index, title: tab.title, url: tab.url})),
        groups: groups.map(group => ({id: group.id, name: group.title, color: group.color, window_id: group.windowId})),
    };
}"""


def proposal_input(request: dict) -> dict:
    """Read the tab context from LangChain's user message."""
    message = next(message for message in request["input"] if message["role"] == "user")
    return json.loads(message["content"])
