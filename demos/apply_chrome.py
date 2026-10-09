import argparse
import asyncio
import os
from tempfile import TemporaryDirectory

from langchain.messages import AIMessage, ToolMessage
from playwright.async_api import BrowserContext, async_playwright

from aiorganize.agent import build_agent
from aiorganize.chrome_groups import GROUP_BROWSER_ARGS, apply_groups, load_group_extension
from aiorganize.proposal import GroupingProposal, print_preview
from aiorganize.terminal import print_message
from aiorganize.tools import chrome_read_tab_tool, chrome_tab_tool
from demos.fixtures import EXTENSION_PATH, create_test_tabs


async def propose_groups(context: BrowserContext, request: str) -> GroupingProposal:
    agent = build_agent(chrome_tab_tool(context), chrome_read_tab_tool(context), structured=True)
    proposal = None
    async for update in agent.astream(
        {"messages": [{"role": "user", "content": request}]},
        stream_mode="updates",
        config={"recursion_limit": 30},
    ):
        for step in update.values():
            if step is None:
                continue
            for message in step.get("messages", []):
                # The validated proposal gets its own readable preview below.
                if isinstance(message, ToolMessage) or (
                    isinstance(message, AIMessage) and message.tool_calls
                ):
                    print_message(message)
            if "structured_response" in step:
                proposal = step["structured_response"]
    if not isinstance(proposal, GroupingProposal):
        raise RuntimeError("The agent did not produce a structured grouping proposal.")
    return proposal


async def run_demo(*, headless: bool) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Run with: make apply-chrome")

    async with async_playwright() as playwright:
        with TemporaryDirectory(prefix="aiorganize-apply-") as profile:
            context = await playwright.chromium.launch_persistent_context(
                profile,
                channel="chrome",
                headless=headless,
                args=GROUP_BROWSER_ARGS,
                ignore_default_args=["--disable-extensions"],
            )
            try:
                worker = await load_group_extension(context, EXTENSION_PATH)
                await create_test_tabs(context)
                await context.new_page()
                request = "Inspect ambiguous tabs and propose topic groups for all the tabs."
                while True:
                    snapshot = await chrome_tab_tool(context).ainvoke({})
                    proposal = await propose_groups(context, request)
                    proposal.validate_tabs(snapshot)
                    print_preview(proposal, snapshot)
                    while True:
                        decision = await asyncio.to_thread(input, "\nType approve, reject, or changes: ")
                        decision = decision.strip().casefold()
                        if decision in {"approve", "reject", "changes"}:
                            break

                    if decision == "reject":
                        print("Rejected. No groups were applied.")
                        break
                    if decision == "changes":
                        feedback = await asyncio.to_thread(input, "What should change? ")
                        request = (
                            "Inspect ambiguous tabs and propose topic groups for all the tabs. "
                            f"Previous proposal: {proposal.model_dump_json()}. "
                            f"Requested changes: {feedback}"
                        )
                        continue

                    state = await apply_groups(worker, proposal, snapshot, approved=True)
                    print("\nApplied and verified browser groups:")
                    for group in state["groups"]:
                        print(f"  {group['name']} ({group['color']})")
                    await asyncio.to_thread(input, "\nInspect Chrome, then press Enter to end the test: ")
                    break
            except EOFError:
                print("\nInput ended. Closing the isolated test browser.")
            finally:
                await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and apply groups in isolated Chrome.")
    parser.add_argument("--headless", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(run_demo(headless=arguments.headless))
