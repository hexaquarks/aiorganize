from pathlib import Path

from playwright.async_api import BrowserContext, Error, Page, Worker

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


async def open_group_control_page(
    context: BrowserContext, extension_path: Path | None = None
) -> Page:
    """Open a control page without relying on a running extension service worker."""
    extension_urls = []
    if extension_path is not None:
        if context.browser is None:
            raise RuntimeError("A browser connection is required to load the extension.")
        session = await context.browser.new_browser_cdp_session()
        try:
            result = await session.send(
                "Extensions.loadUnpacked", {"path": str(extension_path.resolve())}
            )
            extension_urls.append(f"chrome-extension://{result['id']}/control.html")
        except Error as error:
            # Older Chrome builds only allow this command over a debugging pipe.
            if "Method not available" not in str(error):
                raise RuntimeError("Chrome could not load the local grouping extension.") from error
        finally:
            await session.detach()

    extension_urls.extend(
        worker.url.removesuffix("background.js") + "control.html"
        for worker in context.service_workers
        if worker.url.startswith("chrome-extension://") and worker.url.endswith("/background.js")
    )
    for control_url in dict.fromkeys(extension_urls):
        page = await context.new_page()
        try:
            await page.goto(control_url)
            if await page.evaluate("() => chrome.runtime.getManifest().name") == "AI Organize Groups":
                return page
        except Error:
            pass
        await page.close()
    raise RuntimeError(
        "Could not open the AI Organize extension in this Chrome profile. "
        "Update Chrome or load the repository's extension/ directory from chrome://extensions."
    )


async def apply_groups(
    worker: Worker | Page,
    proposal: GroupingProposal,
    snapshot: list[dict[str, str]],
    *,
    approved: bool,
    window_id: int | None = None,
) -> dict:
    """Apply only an approved, validated proposal, then verify the browser's actual groups."""
    if not approved:
        raise ValueError("Approval is required before applying groups.")
    proposal.validate_tabs(snapshot)
    state = await worker.evaluate(
        "(request) => applyApprovedGroups(request)",
        {
            "groups": [group.model_dump() for group in proposal.ordered_groups()],
            "snapshot": snapshot,
            "window_id": window_id,
        },
    )
    window_tabs = (
        [tab for tab in state["tabs"] if tab["window_id"] == window_id]
        if window_id is not None
        else state["tabs"]
    )
    by_id = {tab["id"]: tab for tab in window_tabs}
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
