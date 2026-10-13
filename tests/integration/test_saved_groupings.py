import asyncio
import json
from datetime import datetime

from playwright.async_api import expect

from tests.fixtures import PRIVATE_PAGE_TEXT, TAB_STATE
from tests.integration.test_panel import PanelTestCase


class SavedGroupingsTest(PanelTestCase):
    async def install_saved_groupings_fixture(
        self, *, connected=True, embedding_status=200, write_status=200, invalid=False,
    ):
        await self.install_proposal_fixture(invalid=invalid)
        self.embedding_requests = []
        self.database_requests = []
        self.write_status = write_status
        self.embedding_status = embedding_status
        self.saved_points = {}
        self.user_id = "661f4c48-e00e-4d83-8126-a3a78fd3dd10"
        await self.panel.evaluate(
            "userId => chrome.storage.local.set({savedGroupingsUserId: userId})", self.user_id,
        )
        self.query_status = 200
        self.query_result = None

        if connected:
            await self.panel.evaluate("""() => chrome.storage.session.set({qdrant: {
                url: 'https://test.cloud.qdrant.io:6333', apiKey: 'qdrant-test-key',
                verifiedAt: '2026-10-12T12:00:00Z',
            }})""")

        async def embed(route):
            self.embedding_requests.append(route.request.post_data_json)
            if self.embedding_status != 200:
                await route.fulfill(status=self.embedding_status, json={"error": {"message": "provider-secret"}})
                return

            await route.fulfill(json={
                "model": "text-embedding-3-small",
                "data": [
                    {"index": index, "embedding": [1] + [0] * 1535}
                    for index in range(len(route.request.post_data_json["input"]))
                ],
            })

        async def database(route):
            request = route.request
            self.database_requests.append({"method": request.method, "body": request.post_data_json})
            if request.method == "GET":
                await route.fulfill(json={"status": "ok", "result": {
                    "config": {"params": {"vectors": {"size": 1536, "distance": "Cosine"}}},
                    "payload_schema": {
                        "userId": {"data_type": "keyword"},
                        "schemaVersion": {"data_type": "integer"},
                        "embeddingModel": {"data_type": "keyword"},
                        "embeddingDimensions": {"data_type": "integer"},
                    },
                }})
                return

            if request.url.endswith("/points/query"):
                if self.query_status != 200:
                    await route.fulfill(status=self.query_status, json={"error": "provider-secret"})
                    return

                result = self.query_result
                if result is None:
                    query_user = request.post_data_json["filter"]["must"][0]["match"]["value"]
                    result = {"points": [
                        {"id": point["id"], "score": 0.9, "payload": point["payload"]}
                        for point in self.saved_points.values()
                        if point["payload"].get("userId") == query_user
                    ]}
                await route.fulfill(json={"status": "ok", "result": result})
                return

            if self.write_status != 200:
                await route.fulfill(status=self.write_status, json={"status": {"error": "provider-secret"}})
                return

            await route.fulfill(json={"status": "ok", "result": {"status": "completed"}})
            for point in request.post_data_json["points"]:
                self.saved_points[point["id"]] = point

        await self.panel.route("https://api.openai.com/v1/embeddings", embed)
        await self.panel.route("https://test.cloud.qdrant.io:6333/**", database)

    async def approve(self):
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()

    def assert_no_saved_grouping_writes(self):
        self.assertFalse(any(request["method"] == "PUT" for request in self.database_requests))
        for request in self.embedding_requests:
            for text in request["input"]:
                self.assertNotIn("name", json.loads(text))

    async def test_only_applied_approvals_save_the_expected_groups(self):
        await self.install_saved_groupings_fixture()
        await self.organize()
        snapshot = (await self.panel.evaluate(TAB_STATE))["tabs"]

        self.assert_no_saved_grouping_writes()
        await self.panel.get_by_role("button", name="Discard", exact=True).click()

        self.assert_no_saved_grouping_writes()
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        await expect(self.panel.locator("#retry-save-groupings")).to_have_count(0)
        writes = [request["body"] for request in self.database_requests if request["method"] == "PUT"]
        self.assertEqual(len(writes), 1)
        points = writes[0]["points"]
        self.assertEqual([point["payload"]["name"] for point in points], ["Dev", "Other"])
        expected_pages = [{"title": tab["title"], "url": tab["url"]} for tab in snapshot]
        actual_pages = [page for point in points for page in point["payload"]["pages"]]
        self.assertCountEqual(actual_pages, expected_pages)
        by_name = {point["payload"]["name"]: point["payload"]["pages"] for point in points}
        self.assertEqual(by_name, {"Dev": expected_pages[:2], "Other": expected_pages[2:]})
        for point in points:
            payload = point["payload"]
            self.assertEqual(set(payload), {
                "userId", "name", "pages", "approvedAt", "schemaVersion", "embeddingModel", "embeddingDimensions",
            })
            self.assertEqual(payload["userId"], self.user_id)
            datetime.fromisoformat(payload["approvedAt"])
        uploaded = json.dumps([self.embedding_requests, writes])
        for excluded in (PRIVATE_PAGE_TEXT, "qdrant-test-key", "test-secret", "chrome_id", "tab-"):
            self.assertNotIn(excluded, uploaded)

        await self.panel.set_viewport_size({"width": 360, "height": 800})
        self.assertTrue(await self.panel.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
        await self.panel.screenshot(path="dist/saved-groupings-preview.png", full_page=True)

    async def test_invalid_proposals_do_not_start_saved_grouping_requests(self):
        await self.install_saved_groupings_fixture(invalid=True)
        await self.panel.locator("#organize").click()

        await expect(self.panel.locator("#status")).to_contain_text("duplicate")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        self.assert_no_saved_grouping_writes()

    async def test_saved_groupings_stay_scoped_to_the_approved_window(self):
        await self.install_saved_groupings_fixture()
        other_window = await self.panel.evaluate("() => chrome.windows.create({url: 'about:blank'})")
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        writes = [request["body"] for request in self.database_requests if request["method"] == "PUT"]
        pages = [page for point in writes[0]["points"] for page in point["payload"]["pages"]]
        self.assertEqual(len(pages), 6)
        self.assertNotIn("about:blank", [page["url"] for page in pages])
        state = await self.panel.evaluate(TAB_STATE)
        other_tabs = [tab for tab in state["tabs"] if tab["window_id"] == other_window["id"]]
        self.assertTrue(all(tab["group_id"] == -1 for tab in other_tabs))

    async def test_disconnected_database_keeps_organization_working_without_embedding(self):
        await self.install_saved_groupings_fixture(connected=False)
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_be_hidden()
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        self.assertEqual(self.embedding_requests, [])
        self.assertEqual(self.database_requests, [])
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_stale_preview_and_partial_application_never_save(self):
        await self.install_saved_groupings_fixture()
        await self.organize()
        await self.context.pages[0].goto("about:blank")
        await self.approve()

        await expect(self.panel.locator("#status")).to_contain_text("Tabs changed after preview")
        self.assert_no_saved_grouping_writes()

        await self.organize()
        await self.panel.evaluate("""() => {
            const update = chrome.tabGroups.update.bind(chrome.tabGroups);
            let calls = 0;
            chrome.tabGroups.update = async (...args) => {
                calls += 1;
                if (calls === 2) {
                    throw new Error('Chrome update failed');
                }
                return update(...args);
            };
        }""")
        await self.approve()

        await expect(self.panel.locator("#status")).to_contain_text("Application stopped")
        self.assert_no_saved_grouping_writes()

    async def test_failed_save_can_retry_without_reapplying_tabs_or_changing_ids(self):
        await self.install_saved_groupings_fixture(write_status=503)
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_contain_text("Groupings weren’t saved")
        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        self.assertNotIn("provider-secret", await self.panel.locator("#saved-groupings-status").inner_text())
        applied = await self.panel.evaluate(TAB_STATE)
        self.write_status = 200
        await self.panel.locator("#retry-save-groupings").click()

        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        self.assertEqual(await self.panel.evaluate(TAB_STATE), applied)
        writes = [request["body"] for request in self.database_requests if request["method"] == "PUT"]
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0], writes[1])

    async def test_embedding_failure_is_recoverable_without_database_writes(self):
        await self.install_saved_groupings_fixture(embedding_status=401)
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_contain_text("Groupings weren’t saved")
        self.assertFalse(any(request["method"] == "PUT" for request in self.database_requests))
        self.embedding_status = 200
        await self.panel.locator("#retry-save-groupings").click()

        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")

    async def test_saving_blocks_duplicate_actions_and_new_proposals_clear_old_save_failures(self):
        await self.install_saved_groupings_fixture()
        await self.panel.unroute("https://api.openai.com/v1/embeddings")
        release = asyncio.Event()
        self.addCleanup(release.set)

        async def delayed_embedding(route):
            inputs = route.request.post_data_json["input"]
            if "name" not in json.loads(inputs[0]):
                await route.fulfill(json={
                    "model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [1] + [0] * 1535}],
                })
                return

            await release.wait()
            await route.fulfill(status=503, json={"error": {"message": "provider-secret"}})

        await self.panel.route("https://api.openai.com/v1/embeddings", delayed_embedding)
        await self.organize()
        await self.approve()

        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Saving approved groupings…")
        await expect(self.panel.locator("#organize")).to_be_disabled()
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await expect(self.panel.locator("#settings-toggle")).to_be_disabled()
        release.set()

        await expect(self.panel.locator("#retry-save-groupings")).to_be_visible()
        await self.organize()

        await expect(self.panel.locator("#retry-save-groupings")).to_have_count(0)
        await expect(self.panel.locator("#saved-groupings-status")).to_be_hidden()
