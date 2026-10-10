import argparse
import asyncio
import os
from tempfile import TemporaryDirectory

from langchain.messages import AIMessage, ToolMessage
from playwright.async_api import BrowserContext, Page, Worker, async_playwright

from aiorganize.agent import build_agent
from aiorganize.chrome_groups import GROUP_BROWSER_ARGS, apply_groups, load_group_extension
from aiorganize.proposal import GroupingProposal, print_preview
from aiorganize.terminal import print_message
from aiorganize.tools import chrome_read_tab_tool, chrome_tab_tool
from demos.fixtures import EXTENSION_PATH, create_test_tabs


async def propose_groups(
    context: BrowserContext, request: str, *, worker: Worker | Page | None = None,
    window_id: int | None = None,
) -> GroupingProposal:
    agent = build_agent(
        chrome_tab_tool(context, worker=worker, window_id=window_id),
        chrome_read_tab_tool(context, worker=worker, window_id=window_id),
        structured=True,
    )
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


async def review_and_apply(
    context: BrowserContext, worker: Worker | Page, *, window_id: int | None = None
) -> None:
    request = "Inspect ambiguous tabs and propose topic groups for all the tabs."
    while True:
        selected_worker = worker if window_id is not None else None
        snapshot = await chrome_tab_tool(
            context, worker=selected_worker, window_id=window_id
        ).ainvoke({})
        if not snapshot:
            print("The selected Chrome window has no accessible tabs.")
            return
        if len(snapshot) == 1 and snapshot[0]["url"] in {"about:blank", "chrome://newtab/"}:
            await asyncio.to_thread(
                input,
                "Open the tabs to organize in Chrome, then press Enter: ",
            )
            continue
        print(f"Found {len(snapshot)} tabs. Asking the model for groups...", flush=True)
        proposal = await propose_groups(
            context, request, worker=selected_worker, window_id=window_id
        )
        proposal.validate_tabs(snapshot)
        print_preview(proposal, snapshot)
        while True:
            decision = await asyncio.to_thread(input, "\nType approve, reject, or changes: ")
            decision = decision.strip().casefold()
            if decision in {"approve", "reject", "changes"}:
                break

        if decision == "reject":
            print("Rejected. No groups were applied.")
            return
        if decision == "changes":
            feedback = await asyncio.to_thread(input, "What should change? ")
            request = (
                "Inspect ambiguous tabs and propose topic groups for all the tabs. "
                f"Previous proposal: {proposal.model_dump_json()}. "
                f"Requested changes: {feedback}"
            )
            continue

        state = await apply_groups(worker, proposal, snapshot, approved=True, window_id=window_id)
        print("\nApplied and verified browser groups:")
        for group in state["groups"]:
            if window_id is None or group["window_id"] == window_id:
                print(f"  {group['name']} ({group['color']})")
        return


async def run_demo(*, headless: bool) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY before running the isolated Chrome demo.")

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
                await review_and_apply(context, worker)
                await asyncio.to_thread(input, "\nInspect Chrome, then press Enter to end the test: ")
            except EOFError:
                print("\nInput ended. Closing the isolated test browser.")
            finally:
                await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and apply groups in isolated Chrome.")
    parser.add_argument("--headless", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(run_demo(headless=arguments.headless))
