import argparse
import asyncio
import json
import os
from html import escape
from tempfile import TemporaryDirectory

from langchain.messages import AIMessage, ToolMessage
from playwright.async_api import Route, async_playwright

from agent import build_agent
from main import print_message
from tools import chrome_tab_tool


TEST_TABS = {
    "https://tabs.test/python": "Python Tutorial",
    "https://tabs.test/langchain": "LangChain Docs",
    "https://tabs.test/chat": "ChatGPT",
    "https://tabs.test/recipes": "Pasta Recipes",
    "https://tabs.test/travel": "Toronto Travel Guide",
}


async def serve_test_page(route: Route) -> None:
    # Keep pages deterministic and offline while preserving realistic browser URLs.
    title = escape(TEST_TABS[route.request.url])
    await route.fulfill(
        content_type="text/html",
        body=f"<!doctype html><title>{title}</title><h1>{title}</h1>",
    )


async def run_test(*, headless: bool, browser_only: bool) -> None:
    if not browser_only and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY or use --browser-only.")

    async with async_playwright() as playwright:
        with TemporaryDirectory(prefix="aiorganize-chrome-") as profile:
            context = await playwright.chromium.launch_persistent_context(
                profile, channel="chrome", headless=headless
            )
            try:
                await context.route("https://tabs.test/**", serve_test_page)
                # Chrome starts with a blank tab; use it for the first test page.
                first_page = context.pages[0] if context.pages else await context.new_page()
                for index, url in enumerate(TEST_TABS):
                    page = first_page if index == 0 else await context.new_page()
                    await page.goto(url)

                tab_tool = chrome_tab_tool(context)
                tabs = await tab_tool.ainvoke({})
                assert len(tabs) == len(TEST_TABS), "Unexpected number of live tabs"
                assert {tab["url"]: tab["title"] for tab in tabs} == TEST_TABS
                assert len({tab["id"] for tab in tabs}) == len(tabs), "Duplicate tab IDs"

                # A new tab must appear on the next call: the tool must read live state.
                await context.new_page()
                expected_tabs = await tab_tool.ainvoke({})
                assert len(expected_tabs) == len(tabs) + 1
                assert {tab["id"] for tab in tabs} < {tab["id"] for tab in expected_tabs}
                print(f"PASS: tool reads {len(expected_tabs)} live Chrome tabs.", flush=True)

                if browser_only:
                    return

                agent = build_agent(tab_tool)
                tool_results = []
                final_answer = ""
                async for update in agent.astream(
                    {"messages": [{"role": "user", "content": "Please list all the tabs."}]},
                    stream_mode="updates",
                    config={"recursion_limit": 10},
                ):
                    for step in update.values():
                        for message in step["messages"]:
                            print_message(message)
                            if isinstance(message, ToolMessage):
                                assert message.name == "list_tabs"
                                assert message.status == "success"
                                assert isinstance(message.content, str)
                                tool_results.append(json.loads(message.content))
                            elif isinstance(message, AIMessage) and not message.tool_calls:
                                final_answer = message.text

                assert tool_results, "Agent did not call list_tabs"
                for result in tool_results:
                    assert result == expected_tabs, "Agent received incorrect tab data"
                for tab in expected_tabs:
                    assert tab["id"] in final_answer, "Final answer omitted a tab ID"
                    assert tab["title"] in final_answer, "Final answer omitted a tab title"
                    assert tab["url"] in final_answer, "Final answer omitted a tab URL"
                assert await tab_tool.ainvoke({}) == expected_tabs, "Browser tabs changed"
                print("PASS: OpenAI called the live tool and listed every tab.", flush=True)
            finally:
                # Dispose of the test browser and temporary profile even after a failure.
                await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test tab listing in an isolated Chrome.")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a window.")
    parser.add_argument("--browser-only", action="store_true", help="Skip the OpenAI call.")
    arguments = parser.parse_args()
    asyncio.run(run_test(headless=arguments.headless, browser_only=arguments.browser_only))
