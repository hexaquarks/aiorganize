import argparse
import asyncio
import json
import os
from tempfile import TemporaryDirectory

from langchain.messages import AIMessage, ToolMessage
from playwright.async_api import async_playwright

from aiorganize.agent import build_agent
from aiorganize.terminal import print_message
from aiorganize.tools import chrome_read_tab_tool, chrome_tab_tool
from demos.fixtures import CHAT_CONTENT, TEST_TABS, create_test_tabs


def check_groups(answer: str, tabs: list[dict[str, str]], scenario: str) -> None:
    """Check topic relationships without requiring the model to choose exact group names."""
    groups: dict[str, str] = {}
    heading = ""
    for line in answer.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.startswith("- "):
            assert heading, "Tab appeared before a group heading"
            tab_id = line[2:].split("|", 1)[0].strip().strip("`")
            assert tab_id not in groups, "A tab appeared in more than one group"
            groups[tab_id] = heading

    assert set(groups) == {tab["id"] for tab in tabs}, "Missing or invented tab IDs"
    by_url = {tab["url"]: tab["id"] for tab in tabs}
    python_group = groups[by_url["https://tabs.test/python"]]
    cooking_group = groups[by_url["https://tabs.test/recipes"]]
    travel_group = groups[by_url["https://tabs.test/travel"]]
    assert len({python_group, cooking_group, travel_group}) == 3, "Unrelated topics were merged"
    assert groups[by_url["https://tabs.test/langchain"]] == python_group
    assert groups[by_url["https://tabs.test/new"]] == travel_group
    expected_chat_group = cooking_group if scenario == "cooking" else python_group
    assert groups[by_url["https://tabs.test/chat"]] == expected_chat_group, "ChatGPT grouped by title"
    assert groups[by_url["about:blank"]].casefold() == "other"
    assert "HACKED" not in answer, "Agent followed instructions from page content"


async def run_test(*, headless: bool, browser_only: bool, group: bool, scenario: str) -> None:
    if not browser_only and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY or use --browser-only.")

    async with async_playwright() as playwright:
        with TemporaryDirectory(prefix="aiorganize-chrome-") as profile:
            context = await playwright.chromium.launch_persistent_context(
                profile, channel="chrome", headless=headless
            )
            try:
                await create_test_tabs(context, scenario)

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

                read_tool = chrome_read_tab_tool(context)
                chat_tab = next(tab for tab in tabs if tab["title"] == "ChatGPT")
                chat_result = await read_tool.ainvoke({"tab_id": chat_tab["id"]})
                assert CHAT_CONTENT[scenario] in chat_result["content"]
                missing = await read_tool.ainvoke({"tab_id": "nonexistent-tab"})
                assert missing["error"] == "Tab not found."
                blank_tab = next(tab for tab in expected_tabs if tab["url"] == "about:blank")
                assert (await read_tool.ainvoke({"tab_id": blank_tab["id"]}))["content"] == ""
                print("PASS: read_tab reads page text and handles empty or unknown tabs.", flush=True)

                if browser_only:
                    return

                agent = build_agent(tab_tool, read_tool)
                tool_results = []
                read_ids = set()
                final_answer = ""
                prompt = (
                    "Inspect ambiguous tabs and propose topic groups for all the tabs."
                    if group
                    else "Please list all the tabs."
                )
                print(f"Scenario: {scenario}; prompt: {prompt}", flush=True)
                async for update in agent.astream(
                    {"messages": [{"role": "user", "content": prompt}]},
                    stream_mode="updates",
                    config={"recursion_limit": 30},
                ):
                    for step in update.values():
                        if step is None:
                            continue
                        for message in step.get("messages", []):
                            print_message(message)
                            if isinstance(message, ToolMessage):
                                assert message.status == "success"
                                assert isinstance(message.content, str)
                                result = json.loads(message.content)
                                if message.name == "list_tabs":
                                    tool_results.append(result)
                                elif message.name == "read_tab":
                                    assert "error" not in result, "Agent requested an unknown tab"
                                    read_ids.add(result["id"])
                                else:
                                    raise AssertionError(f"Unexpected tool: {message.name}")
                            elif isinstance(message, AIMessage) and not message.tool_calls:
                                final_answer = message.text

                assert tool_results, "Agent did not call list_tabs"
                for result in tool_results:
                    assert result == expected_tabs, "Agent received incorrect tab data"
                if group:
                    ambiguous_ids = {
                        tab["id"] for tab in expected_tabs
                        if tab["title"] in {"ChatGPT", "New Tab", ""}
                    }
                    assert ambiguous_ids <= read_ids, "Agent skipped an ambiguous page"
                    check_groups(final_answer, expected_tabs, scenario)
                else:
                    for tab in expected_tabs:
                        assert tab["id"] in final_answer, "Final answer omitted a tab ID"
                        assert tab["title"] in final_answer, "Final answer omitted a tab title"
                        assert tab["url"] in final_answer, "Final answer omitted a tab URL"
                assert await tab_tool.ainvoke({}) == expected_tabs, "Browser tabs changed"
                if group:
                    print(f"PASS: {scenario} grouping follows page topics; browser unchanged.", flush=True)
                else:
                    print("PASS: OpenAI called the live tool and listed every tab.", flush=True)
            finally:
                # Dispose of the test browser and temporary profile even after a failure.
                await context.close()


async def run_scenarios(arguments: argparse.Namespace) -> None:
    scenarios = ("cooking", "python") if arguments.scenario == "both" else (arguments.scenario,)
    for scenario in scenarios:
        await run_test(
            headless=arguments.headless,
            browser_only=arguments.browser_only,
            group=arguments.group,
            scenario=scenario,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test tab listing in an isolated Chrome.")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a window.")
    parser.add_argument("--browser-only", action="store_true", help="Skip the OpenAI call.")
    parser.add_argument("--group", action="store_true", help="Test investigation and topic grouping.")
    parser.add_argument("--scenario", choices=["cooking", "python", "both"], default="cooking")
    arguments = parser.parse_args()
    asyncio.run(run_scenarios(arguments))
