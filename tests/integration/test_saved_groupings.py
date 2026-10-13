import json

from playwright.async_api import expect

from tests.fixtures import TAB_STATE, PRIVATE_PAGE_TEXT
from tests.integration.test_panel import PanelTestCase


class SavedGroupingsTest(PanelTestCase):
    async def test_only_approved_groups_are_saved_through_the_app_api(self):
        await self.install_proposal_fixture()
        requests = []
        self.panel.on("request", lambda request: requests.append(request))
        await self.organize()
        self.assertEqual(self.database.count(self.store.collection).count, 0)
        await self.panel.locator("#reject").click()
        self.assertEqual(self.database.count(self.store.collection).count, 0)

        await self.organize()
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        points, _ = self.database.scroll(self.store.collection, with_payload=True)
        self.assertEqual({point.payload["name"] for point in points}, {"Dev", "Other"})
        self.assertEqual(len({point.payload["userId"] for point in points}), 1)
        writes = [request for request in requests if request.url.endswith("/v1/groupings")]
        self.assertEqual(len(writes), 1)
        self.assertIn("authorization", writes[0].headers)
        body = writes[0].post_data_json
        self.assertEqual(set(body), {"groups"})
        for group in body["groups"]:
            self.assertEqual(set(group), {"name", "pages", "approvedAt", "vector"})
        for excluded in (PRIVATE_PAGE_TEXT, "test-secret", "userId", "qdrant", "chrome_id"):
            self.assertNotIn(excluded, json.dumps(body))
        self.assertFalse(any("qdrant" in request.url for request in requests))

        await self.organize()
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        self.assertEqual(self.database.count(self.store.collection).count, 2)

    async def test_save_failure_retries_without_reapplying_tabs(self):
        await self.install_proposal_fixture()
        async def unavailable(route):
            await route.fulfill(status=503, json={"detail": "provider-secret"})
        await self.panel.route("http://127.0.0.1:8765/v1/groupings", unavailable)
        await self.organize()
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#retry-save-groupings")).to_be_visible()
        applied = await self.panel.evaluate(TAB_STATE)
        self.assertNotIn("provider-secret", await self.panel.locator("body").inner_text())
        self.assertEqual(self.database.count(self.store.collection).count, 0)
        await self.panel.unroute("http://127.0.0.1:8765/v1/groupings", unavailable)
        await self.panel.locator("#retry-save-groupings").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        self.assertEqual(await self.panel.evaluate(TAB_STATE), applied)

    async def test_failed_or_stale_approval_does_not_save(self):
        await self.install_proposal_fixture()
        await self.organize()
        await self.context.pages[0].close()
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#status")).to_contain_text("Tabs changed")
        self.assertEqual(self.database.count(self.store.collection).count, 0)

    async def test_legacy_database_credentials_are_removed_on_startup(self):
        await self.panel.evaluate("""async () => {
            await chrome.storage.local.set({qdrant: {apiKey: 'legacy-secret'}});
            await chrome.storage.session.set({qdrant: {apiKey: 'legacy-secret'}});
        }""")
        await self.panel.reload()
        await expect(self.panel.locator("#api-settings")).to_be_visible()
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertNotIn("legacy-secret", json.dumps(stores))
        self.assertNotIn("Qdrant", await self.panel.locator("body").inner_text())
