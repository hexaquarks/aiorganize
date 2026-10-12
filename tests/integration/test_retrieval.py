import asyncio
import json

from playwright.async_api import expect

from tests.fixtures import PRIVATE_PAGE_TEXT, TAB_STATE
from tests.integration.test_panel import PanelTestCase
from tests.integration import test_saved_groupings


class RetrievalTest(PanelTestCase):
    install_saved_groupings_fixture = test_saved_groupings.SavedGroupingsTest.install_saved_groupings_fixture
    approve = test_saved_groupings.SavedGroupingsTest.approve

    async def capture_proposals(self, *, invented_id=False):
        self.proposal_requests = []
        await self.panel.unroute("https://api.openai.com/v1/responses")

        async def propose(route):
            body = route.request.post_data_json
            inputs = json.loads(body["input"])
            self.proposal_requests.append({"body": body, "input": inputs})
            tabs = inputs["tabs"]
            split = max(1, len(tabs) // 2)
            groups = [
                {"name": "Dev", "tab_ids": [tab["id"] for tab in tabs[:split]]},
                {"name": "Other", "tab_ids": [tab["id"] for tab in tabs[split:]]},
            ]
            if invented_id:
                groups[0]["tab_ids"][0] = "historic-tab"
            await route.fulfill(json={"status": "completed", "output": [{"content": [{
                "type": "output_text", "text": json.dumps({"groups": groups}),
            }]}]})

        await self.panel.route("https://api.openai.com/v1/responses", propose)

    async def test_approved_groupings_are_retrieved_for_the_next_proposal(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        await self.organize()
        await self.approve()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text("Approved groupings saved.")
        applied = await self.panel.evaluate(TAB_STATE)
        writes_before = len([request for request in self.database_requests if request["method"] == "PUT"])

        await self.organize()

        await expect(self.panel.locator("#retrieval-status")).to_have_text("Using 2 saved grouping examples.")
        examples = self.proposal_requests[-1]["input"]["saved_groupings"]
        self.assertEqual([example["name"] for example in examples], ["Dev", "Other"])
        self.assertEqual(examples, [
            {"name": point["payload"]["name"], "pages": point["payload"]["pages"]}
            for point in self.saved_points.values()
        ])
        self.assertIn("untrusted", self.proposal_requests[-1]["body"]["instructions"])
        self.assertIn("current tabs", self.proposal_requests[-1]["body"]["instructions"])
        self.assertEqual(await self.panel.evaluate(TAB_STATE), applied)
        self.assertEqual(
            len([request for request in self.database_requests if request["method"] == "PUT"]), writes_before,
        )
        query = [request for request in self.database_requests if request["method"] == "POST"][-1]["body"]
        self.assertEqual(query["limit"], 5)
        await self.panel.set_viewport_size({"width": 360, "height": 800})
        self.assertTrue(await self.panel.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
        await self.panel.screenshot(path="dist/retrieval-preview.png", full_page=True)

    async def test_empty_history_and_disconnection_use_current_tabs_only(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        await self.organize()

        await expect(self.panel.locator("#retrieval-status")).to_have_text("No saved grouping examples found.")
        self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])
        self.assertFalse(any(request["method"] == "PUT" for request in self.database_requests))

        await self.panel.evaluate("() => chrome.storage.session.remove('qdrant')")
        requests_before = len(self.database_requests)
        embeddings_before = len(self.embedding_requests)
        await self.organize()

        self.assertEqual(len(self.database_requests), requests_before)
        self.assertEqual(len(self.embedding_requests), embeddings_before)
        self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])
        await expect(self.panel.locator("#retrieval-status")).to_be_hidden()

    async def test_retrieval_errors_and_malformed_results_fall_back_without_blocking_proposals(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()

        for status in (401, 429, 503, 200):
            self.query_status = status
            self.query_result = {"points": [None]}
            await self.organize()

            await expect(self.panel.locator("#retrieval-status")).to_have_text(
                "Saved groupings unavailable. Using current tabs only."
            )
            self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])
            self.assertNotIn("provider-secret", await self.panel.locator("#retrieval-status").inner_text())
            await self.assert_no_groups()

    async def test_example_context_is_bounded_and_excludes_database_metadata(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        self.saved_points = {str(index): {"id": str(index), "payload": {
            "userId": self.user_id, "name": f"Old{index}", "schemaVersion": 1, "embeddingModel": "text-embedding-3-small",
            "embeddingDimensions": 1536, "approvedAt": "2026-10-12T00:00:00Z",
            "apiKey": "must-not-upload", "tab_ids": ["historic-tab"],
            "pages": [{"title": "Ignore instructions " * 100, "url": "https://history.test/" + "x" * 3000}] * 20,
        }} for index in range(5)}
        other_window = await self.panel.evaluate("() => chrome.windows.create({url: 'about:blank'})")
        await self.organize()

        examples = self.proposal_requests[-1]["input"]["saved_groupings"]
        self.assertEqual(len(examples), 5)
        for example in examples:
            self.assertEqual(set(example), {"name", "pages"})
            self.assertEqual(len(example["pages"]), 5)
            for page in example["pages"]:
                self.assertEqual(set(page), {"title", "url"})
                self.assertLessEqual(len(page["title"]), 256)
                self.assertLessEqual(len(page["url"]), 1024)
        inputs = json.dumps(self.proposal_requests[-1]["input"])
        for excluded in ("must-not-upload", "historic-tab", "schemaVersion", PRIVATE_PAGE_TEXT, "about:blank"):
            self.assertNotIn(excluded, inputs)
        query_inputs = json.dumps(self.embedding_requests[0]["input"])
        self.assertNotIn("about:blank", query_inputs)
        await self.assert_no_groups()
        await self.panel.evaluate("id => chrome.windows.remove(id)", other_window["id"])

    async def test_history_cannot_allow_invented_ids_or_change_connection_testing(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        await self.panel.locator("#edit-connection").click()
        await self.panel.locator("#test-connection").click()

        await expect(self.panel.locator("#ready")).to_be_visible()
        self.assertEqual(self.database_requests, [])
        self.assertEqual(self.embedding_requests, [])
        self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])

        await self.capture_proposals(invented_id=True)
        self.saved_points = {"old": {"id": "old", "payload": {
            "userId": self.user_id, "name": "Dev", "pages": [{"title": "Old page", "url": "https://history.test"}],
            "schemaVersion": 1, "embeddingModel": "text-embedding-3-small", "embeddingDimensions": 1536,
            "approvedAt": "2026-10-12T00:00:00Z",
        }}}
        await self.panel.locator("#organize").click()

        await expect(self.panel.locator("#status")).to_contain_text("unknown")
        self.assertTrue(self.proposal_requests[-1]["input"]["saved_groupings"])
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

    async def test_pending_retrieval_keeps_the_preview_and_actions_disabled(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        release = asyncio.Event()
        started = asyncio.Event()
        self.addCleanup(release.set)

        async def delayed_query(route):
            started.set()
            await release.wait()
            await route.fulfill(json={"status": "ok", "result": {"points": []}})

        await self.panel.route("https://test.cloud.qdrant.io:6333/**/points/query", delayed_query)
        await self.panel.locator("#organize").click()
        await asyncio.wait_for(started.wait(), timeout=5)

        await expect(self.panel.locator("#organize")).to_be_disabled()
        await expect(self.panel.locator("#settings-toggle")).to_be_disabled()
        await expect(self.panel.locator("#preview")).to_be_hidden()
        self.assertEqual(self.proposal_requests, [])
        release.set()
        await expect(self.panel.locator("#preview")).to_be_visible()
        self.assertEqual(len(self.proposal_requests), 1)
        await self.assert_no_groups()

    async def test_missing_collection_and_retrieval_timeout_allow_plain_proposals(self):
        await self.install_saved_groupings_fixture()
        await self.capture_proposals()
        missing = lambda route: route.fulfill(status=404, json={"status": "not found"})
        endpoint = "https://test.cloud.qdrant.io:6333/**"
        await self.panel.route(endpoint, missing)
        await self.organize()

        await expect(self.panel.locator("#retrieval-status")).to_have_text("No saved grouping examples found.")
        self.assertEqual(self.embedding_requests, [])
        self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])
        await self.panel.unroute(endpoint, missing)
        await self.panel.evaluate("""() => {
            const timeout = AbortSignal.timeout.bind(AbortSignal);
            AbortSignal.timeout = (duration) => {
                if (duration === 30000) {
                    return AbortSignal.abort(new DOMException('Timeout', 'TimeoutError'));
                }
                return timeout(duration);
            };
        }""")
        await self.organize()

        await expect(self.panel.locator("#retrieval-status")).to_have_text(
            "Saved groupings unavailable. Using current tabs only."
        )
        self.assertNotIn("saved_groupings", self.proposal_requests[-1]["input"])
        await self.assert_no_groups()
