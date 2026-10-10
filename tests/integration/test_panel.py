import tempfile
import unittest

from playwright.async_api import async_playwright, expect

from aiorganize.chrome_groups import GROUP_BROWSER_ARGS, load_group_extension
from demos.fixtures import EXTENSION_PATH, create_test_tabs


class PanelTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="aiorganize-panel-test-")
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
        self.panel = await self.context.new_page()
        await self.panel.goto(self.worker.url.removesuffix("background.js") + "panel.html")
        await self.panel.wait_for_function("document.querySelector('#approve').disabled")

    async def install_proposal_fixture(self, *, invalid=False, delayed=False):
        # Fake proposals live only in tests; the installed extension never fabricates AI results.
        await self.panel.evaluate(
            """async ({invalid, delayed}) => {
                const {panel} = await import('./panel-entry.js');
                const {mountPanel} = await import('./panel.js');
                panel.destroy();
                mountPanel(document, async ({snapshot}) => {
                    if (delayed) await new Promise(resolve => { window.resolveProposal = resolve; });
                    const groups = [
                        {name: 'Other', tab_ids: snapshot.slice(2).map(tab => tab.id)},
                        {name: 'Dev', tab_ids: snapshot.slice(0, 2).map(tab => tab.id)},
                    ];
                    if (invalid) groups[1].tab_ids.push(snapshot[2].id);
                    return {groups};
                });
            }""",
            {"invalid": invalid, "delayed": delayed},
        )

    async def organize(self):
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.locator("#preview")).to_be_visible()

    async def assert_no_groups(self):
        state = await self.worker.evaluate("() => tabGroupState()")
        self.assertEqual(state["groups"], [])
        self.assertTrue(all(tab["group_id"] == -1 for tab in state["tabs"]))


class ExtensionPanelTest(PanelTestCase):
    async def test_disconnected_agent_reports_error_without_mutations(self):
        self.assertTrue(await self.worker.evaluate(
            "async () => (await chrome.sidePanel.getPanelBehavior()).openPanelOnActionClick"
        ))
        await self.panel.evaluate("""async () => {
            const {panel} = await import('./panel-entry.js');
            const {mountPanel} = await import('./panel.js');
            const {requestProposal} = await import('./proposal-client.js');
            panel.destroy();
            mountPanel(document, request => requestProposal(request, {hostName: 'com.aiorganize.not_installed'}));
        }""")
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("Python companion unavailable")
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

    async def test_preview_rejection_and_explicit_approval(self):
        await self.install_proposal_fixture()
        await self.organize()
        self.assertEqual(await self.panel.locator("#groups h3").all_text_contents(), ["Dev", "Other"])
        await expect(self.panel.locator("#summary")).to_have_text("6 tabs in 2 groups.")
        await self.assert_no_groups()
        await self.panel.get_by_role("button", name="Reject", exact=True).click()
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await self.assert_no_groups()

        await self.organize()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_have_text("Your tabs are organized.")
        await expect(self.panel.locator("#preview")).to_be_hidden()
        state = await self.worker.evaluate("() => tabGroupState()")
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})
        self.assertTrue(all(tab["group_id"] != -1 for tab in state["tabs"]))

    async def test_added_tab_invalidates_preview_before_mutation(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.context.new_page()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("Tabs were added after preview")
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await self.assert_no_groups()

    async def test_invalid_proposal_cannot_be_approved(self):
        await self.install_proposal_fixture(invalid=True)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("duplicate")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

    async def test_busy_state_and_untrusted_titles(self):
        await self.context.pages[0].evaluate(
            "document.title = '<img src=x onerror=alert(1)>'"
        )
        await self.install_proposal_fixture(delayed=True)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await self.panel.wait_for_function("typeof window.resolveProposal === 'function'")
        await expect(self.panel.locator("#organize")).to_be_disabled()
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.panel.evaluate("window.resolveProposal()")
        await expect(self.panel.locator("#preview")).to_be_visible()
        await expect(self.panel.locator(".tab-title").first).to_have_text('<img src=x onerror=alert(1)>')
        self.assertEqual(await self.panel.locator("#groups img").count(), 0)
        await self.assert_no_groups()

    async def test_preview_stays_scoped_to_panel_window(self):
        await self.install_proposal_fixture()
        other_window = await self.worker.evaluate("() => chrome.windows.create({url: 'about:blank'})")
        await self.organize()
        await expect(self.panel.locator("#summary")).to_have_text("6 tabs in 2 groups.")
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_have_text("Your tabs are organized.")
        state = await self.worker.evaluate("() => tabGroupState()")
        other_tabs = [tab for tab in state["tabs"] if tab["window_id"] == other_window["id"]]
        self.assertEqual(len(other_tabs), 1)
        self.assertEqual(other_tabs[0]["group_id"], -1)


if __name__ == "__main__":
    unittest.main()
