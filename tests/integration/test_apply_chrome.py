import tempfile
import unittest

from playwright.async_api import Error, async_playwright

from aiorganize.chrome_groups import GROUP_BROWSER_ARGS, apply_groups, load_group_extension
from aiorganize.proposal import GroupingProposal, TabGroup
from demos.fixtures import EXTENSION_PATH, create_test_tabs
from aiorganize.tools import chrome_tab_tool


class ChromeGroupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="aiorganize-apply-test-")
        self.addCleanup(self.profile.cleanup)
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.profile.name,
            channel="chrome",
            headless=True,
            args=GROUP_BROWSER_ARGS,
            ignore_default_args=["--disable-extensions"],
        )
        self.addAsyncCleanup(self.context.close)
        self.worker = await load_group_extension(self.context, EXTENSION_PATH)
        await create_test_tabs(self.context)
        await self.context.new_page()
        self.snapshot = await chrome_tab_tool(self.context).ainvoke({})
        by_url = {tab["url"]: tab["id"] for tab in self.snapshot}
        self.proposal = GroupingProposal(
            groups=[
                TabGroup(
                    name="Programming",
                    tab_ids=[by_url["https://tabs.test/python"], by_url["https://tabs.test/langchain"]],
                ),
                TabGroup(
                    name="Cooking",
                    tab_ids=[by_url["https://tabs.test/chat"], by_url["https://tabs.test/recipes"]],
                ),
                TabGroup(
                    name="Travel",
                    tab_ids=[by_url["https://tabs.test/new"], by_url["https://tabs.test/travel"]],
                ),
                TabGroup(name="Unsorted", tab_ids=[by_url["about:blank"]]),
            ]
        )

    async def assert_no_groups(self):
        state = await self.worker.evaluate("() => tabGroupState()")
        self.assertEqual(state["groups"], [])
        self.assertTrue(all(tab["group_id"] == -1 for tab in state["tabs"]))

    async def test_approved_groups_are_created_with_names_and_colors(self):
        state = await apply_groups(self.worker, self.proposal, self.snapshot, approved=True)
        self.assertEqual(len(state["tabs"]), len(self.snapshot))
        self.assertEqual(
            {group["name"]: group["color"] for group in state["groups"]},
            {"Programming": "blue", "Cooking": "green", "Travel": "yellow", "Unsorted": "grey"},
        )
        for proposed in self.proposal.groups:
            actual = next(group for group in state["groups"] if group["name"] == proposed.name)
            members = {tab["id"] for tab in state["tabs"] if tab["group_id"] == actual["id"]}
            self.assertEqual(members, set(proposed.tab_ids))

    async def test_rejection_prevents_mutation(self):
        with self.assertRaisesRegex(ValueError, "Approval is required"):
            await apply_groups(self.worker, self.proposal, self.snapshot, approved=False)
        await self.assert_no_groups()

    async def test_changed_page_prevents_all_mutations(self):
        await self.context.pages[0].goto("about:blank")
        with self.assertRaisesRegex(Error, "Tabs changed after preview"):
            await apply_groups(self.worker, self.proposal, self.snapshot, approved=True)
        await self.assert_no_groups()

    async def test_added_tab_prevents_all_mutations(self):
        await self.context.new_page()
        with self.assertRaisesRegex(Error, "Tabs were added after preview"):
            await apply_groups(self.worker, self.proposal, self.snapshot, approved=True)
        await self.assert_no_groups()

    async def test_missing_tab_prevents_all_mutations(self):
        # A vanished target has no mapping to an open Chrome tab.
        missing_id = self.snapshot[0]["id"]
        snapshot = [dict(tab) for tab in self.snapshot]
        snapshot[0]["id"] = "missing-target"
        proposal = self.proposal.model_copy(deep=True)
        for group in proposal.groups:
            group.tab_ids = [
                "missing-target" if tab_id == missing_id else tab_id
                for tab_id in group.tab_ids
            ]
        with self.assertRaisesRegex(Error, "Tabs changed after preview"):
            await apply_groups(self.worker, proposal, snapshot, approved=True)
        await self.assert_no_groups()


if __name__ == "__main__":
    unittest.main()
