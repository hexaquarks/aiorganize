from pathlib import Path

from playwright.async_api import BrowserContext, Worker

from .proposal import GroupingProposal


GROUP_BROWSER_ARGS = ["--enable-unsafe-extension-debugging"]


async def load_group_extension(context: BrowserContext, extension_path: Path) -> Worker:
    """Load the test-only extension into a fresh isolated Chrome profile."""
    if context.browser is None:
        raise RuntimeError("A Playwright-managed browser is required.")
    session = await context.browser.new_browser_cdp_session()
    try:
        # Modern Chrome removed --load-extension; its experimental CDP loader replaces it here.
        async with context.expect_event("serviceworker") as worker_event:
            await session.send(
                "Extensions.loadUnpacked",
                {"path": str(extension_path.resolve())},
            )
        return await worker_event.value
    finally:
        await session.detach()


async def apply_groups(
    worker: Worker,
    proposal: GroupingProposal,
    snapshot: list[dict[str, str]],
    *,
    approved: bool,
) -> dict:
    """Apply only an approved, validated proposal, then verify the browser's actual groups."""
    if not approved:
        raise ValueError("Approval is required before applying groups.")
    proposal.validate_tabs(snapshot)
    state = await worker.evaluate(
        "(request) => applyApprovedGroups(request)",
        {"groups": proposal.model_dump()["groups"], "snapshot": snapshot},
    )
    by_id = {tab["id"]: tab for tab in state["tabs"]}
    groups_by_id = {group["id"]: group for group in state["groups"]}
    if set(by_id) != {tab["id"] for tab in snapshot}:
        raise RuntimeError("The tab set changed while applying groups; inspect the browser.")
    for tab in snapshot:
        current = by_id.get(tab["id"])
        if current is None or current["title"] != tab["title"] or current["url"] != tab["url"]:
            raise RuntimeError("Tabs changed while applying groups; inspect the browser.")
    for group in proposal.groups:
        group_ids = {by_id[tab_id]["group_id"] for tab_id in group.tab_ids}
        if len(group_ids) != 1 or -1 in group_ids:
            raise RuntimeError(f"Group membership verification failed: {group.name}")
        group_id = next(iter(group_ids))
        actual_group = groups_by_id.get(group_id)
        actual_members = {tab["id"] for tab in state["tabs"] if tab["group_id"] == group_id}
        if (
            actual_group is None
            or actual_group["name"] != group.name
            or actual_members != set(group.tab_ids)
        ):
            raise RuntimeError(f"Group verification failed: {group.name}")
    return state
