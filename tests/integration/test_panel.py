import tempfile
import unittest

from playwright.async_api import async_playwright, expect

from src.dev import CHROME_ARGS, load_extension
from tests.fixtures import EXTENSION_PATH, create_test_tabs


class PanelTestCase(unittest.IsolatedAsyncioTestCase):
    extension_path = EXTENSION_PATH

    async def asyncSetUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="aiorganize-panel-test-")
        self.addCleanup(self.profile.cleanup)
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.profile.name,
            channel="chrome",
            headless=True,
            args=CHROME_ARGS,
            ignore_default_args=["--disable-extensions"],
        )
        self.addAsyncCleanup(self.context.close)
        extension_id = await load_extension(self.context, self.extension_path)
        await create_test_tabs(self.context)
        self.panel = await self.context.new_page()
        # Discovery is offline too; no test credentials are sent to OpenAI.
        await self.panel.route("https://api.openai.com/v1/models", lambda route: route.fulfill(json={
            "data": [{"id": "gpt-4.1-mini", "created": 1}, {"id": "gpt-5.5", "created": 0}],
        }))
        await self.panel.goto(f"chrome-extension://{extension_id}/panel.html")
        await self.panel.wait_for_function("document.querySelector('#approve').disabled")

    async def connect(self, *, remember=False, api_key="test-secret"):
        async def respond(route):
            import json
            request = route.request.post_data_json
            tabs = json.loads(request["input"])["tabs"]
            proposal = {"groups": [{"name": "Test", "tab_ids": [tab["id"] for tab in tabs]}]}
            await route.fulfill(json={
                "status": "completed", "output": [{"content": [{
                    "type": "output_text", "text": json.dumps(proposal),
                }]}],
            })

        await self.panel.route("https://api.openai.com/v1/responses", respond)
        await self.panel.locator("#api-key").fill(api_key)
        await self.panel.locator("#remember-key").set_checked(remember)
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#ready")).to_be_visible()

    async def install_proposal_fixture(self, *, invalid=False, delayed=False):
        await self.connect()
        # Fake proposals live only in tests; the installed extension never fabricates AI results.
        await self.panel.evaluate(
            """async ({invalid, delayed}) => {
                const {panel, mountPanel} = await import('./panel.js');
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
        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#preview")).to_be_visible()

    async def assert_no_groups(self):
        state = await self.panel.evaluate("async () => (await import('./tabs.js')).getTabState()")
        self.assertEqual(state["groups"], [])
        self.assertTrue(all(tab["group_id"] == -1 for tab in state["tabs"]))


class ExtensionPanelTest(PanelTestCase):
    async def test_missing_api_key_reports_error_without_mutations(self):
        self.assertTrue(await self.panel.evaluate(
            "async () => (await chrome.sidePanel.getPanelBehavior()).openPanelOnActionClick"
        ))
        await expect(self.panel.locator("#organize")).to_be_disabled()
        await expect(self.panel.locator("#api-settings")).to_be_visible()
        await expect(self.panel.locator("#test-connection")).to_be_disabled()
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
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        await expect(self.panel.locator("#preview")).to_be_hidden()
        state = await self.panel.evaluate("async () => (await import('./tabs.js')).getTabState()")
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})
        self.assertTrue(all(tab["group_id"] != -1 for tab in state["tabs"]))
        self.assertEqual(
            {group["name"]: group["color"] for group in state["groups"]},
            {"Dev": "blue", "Other": "grey"},
        )
        by_group = {group["id"]: group["name"] for group in state["groups"]}
        dev_indices = [tab["index"] for tab in state["tabs"] if by_group[tab["group_id"]] == "Dev"]
        other_indices = [tab["index"] for tab in state["tabs"] if by_group[tab["group_id"]] == "Other"]
        self.assertGreater(min(other_indices), max(dev_indices))

    async def test_navigated_tab_invalidates_preview_before_mutation(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.context.pages[0].goto("about:blank")
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#status")).to_contain_text("Tabs changed after preview")
        await self.assert_no_groups()

    async def test_closed_tab_invalidates_preview_before_mutation(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.context.pages[0].close()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#status")).to_contain_text("Tabs changed after preview")
        await self.assert_no_groups()

    async def test_moved_tab_invalidates_preview_before_mutation(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.panel.evaluate("""async () => {
            const {getTabState} = await import('./tabs.js');
            const {tabs} = await getTabState();
            await chrome.windows.create({tabId: tabs[0].chrome_id});
        }""")
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#status")).to_contain_text("one browser window")
        await self.assert_no_groups()

    async def test_added_tab_invalidates_preview_before_mutation(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.context.new_page()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#status")).to_contain_text("Tabs were added after preview")
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await self.assert_no_groups()

    async def test_invalid_proposal_cannot_be_approved(self):
        await self.install_proposal_fixture(invalid=True)
        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#status")).to_contain_text("duplicate")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

    async def test_busy_state_and_untrusted_titles(self):
        await self.context.pages[0].evaluate(
            "document.title = '<img src=x onerror=alert(1)>'"
        )
        await self.install_proposal_fixture(delayed=True)
        await self.panel.locator("#organize").click()
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
        other_window = await self.panel.evaluate("() => chrome.windows.create({url: 'about:blank'})")
        await self.organize()
        await expect(self.panel.locator("#summary")).to_have_text("6 tabs in 2 groups.")
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        state = await self.panel.evaluate("async () => (await import('./tabs.js')).getTabState()")
        other_tabs = [tab for tab in state["tabs"] if tab["window_id"] == other_window["id"]]
        self.assertEqual(len(other_tabs), 1)
        self.assertEqual(other_tabs[0]["group_id"], -1)


if __name__ == "__main__":
    unittest.main()
