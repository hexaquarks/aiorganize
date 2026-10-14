from playwright.async_api import expect

from tests.fixtures import TAB_STATE, proposal_input
from tests.integration.test_panel import PanelTestCase


class RetrievalTest(PanelTestCase):
    async def test_saved_groups_reach_the_llm_and_survive_panel_reload(self):
        await self.install_proposal_fixture()
        proposals = []
        self.panel.on("request", lambda request: proposals.append(proposal_input(request.post_data_json))
                      if request.url.endswith("/v1/responses") else None)
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        state = await self.panel.evaluate(TAB_STATE)
        token = await self.panel.evaluate("async () => (await chrome.storage.local.get()).savedGroupingsInstallation.token")
        await self.panel.reload()
        await expect(self.panel.locator("#ready")).to_be_visible()
        await self.organize()
        examples = proposals[-1]["saved_groupings"]
        self.assertEqual({example["name"] for example in examples}, {"Dev", "Other"})
        for example in examples:
            self.assertEqual(set(example), {"name", "pages"})
        self.assertEqual(await self.panel.evaluate(TAB_STATE), state)
        self.assertEqual(token, await self.panel.evaluate(
            "async () => (await chrome.storage.local.get()).savedGroupingsInstallation.token"
        ))
        await self.assert_history_is_isolated(proposals)

    async def assert_history_is_isolated(self, proposals):
        await self.panel.locator("#reject").click()
        await self.panel.evaluate("() => chrome.storage.local.remove('savedGroupingsInstallation')")
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])

    async def test_api_failure_falls_back_without_exposing_provider_details(self):
        await self.install_proposal_fixture()
        await self.panel.route("http://127.0.0.1:8765/v1/groupings/search", lambda route: route.fulfill(
            status=503, json={"detail": "database-secret"},
        ))
        await self.organize()
        await expect(self.panel.locator("#retrieval-status")).to_have_text(
            "Saved groupings unavailable. Using current tabs only."
        )
        self.assertNotIn("database-secret", await self.panel.locator("body").inner_text())
        await self.assert_no_groups()

    async def test_missing_backend_cannot_silently_report_saved_groups(self):
        await self.install_proposal_fixture()
        await self.panel.route("http://127.0.0.1:8765/**", lambda route: route.abort())
        await self.organize()
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        await expect(self.panel.locator("#retry-save-groupings")).to_be_visible()
        await expect(self.panel.locator("#saved-groupings-status")).to_contain_text("weren’t saved")
