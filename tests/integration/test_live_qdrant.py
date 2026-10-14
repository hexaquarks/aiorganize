import asyncio
import json
import os
import unittest
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from playwright.async_api import expect
from qdrant_client import QdrantClient, models

from src.api import create_app
from src.groupings import COLLECTION, GroupingsStore
from tests.fixtures import proposal_input
from tests.integration.test_panel import PanelTestCase


TEST_COLLECTION = f"{COLLECTION}_test"


@unittest.skipUnless(os.environ.get("QDRANT_LIVE_TEST") == "1", "Run make test-qdrant for the live database test")
class LiveQdrantTest(PanelTestCase):
    async def test_browser_api_and_real_database_isolate_installations(self):
        database = QdrantClient(
            url=os.environ["QDRANT_ENDPOINT"], api_key=os.environ["QDRANT_API_KEY"],
            timeout=30, check_compatibility=False,
        )
        # The live fixture uses only the dedicated test collection; no production writes.
        store = GroupingsStore(database, TEST_COLLECTION)
        backend = self.enterContext(TestClient(create_app(store, "live-test-signing-secret-" * 3)))
        database.delete(TEST_COLLECTION, models.FilterSelector(filter=models.Filter()), wait=True)

        def cleanup():
            database.delete(TEST_COLLECTION, models.FilterSelector(filter=models.Filter()), wait=True)
            self.assertEqual(database.count(TEST_COLLECTION).count, 0)
        self.addCleanup(cleanup)

        async def through_api(route):
            response = await asyncio.to_thread(
                backend.request, route.request.method, urlparse(route.request.url).path,
                json=route.request.post_data_json, headers=dict(route.request.headers),
            )
            await route.fulfill(status=response.status_code, json=response.json())

        await self.panel.route("http://127.0.0.1:8765/**", through_api)
        await self.install_proposal_fixture()
        proposals = []
        self.panel.on("request", lambda request: proposals.append(proposal_input(request.post_data_json))
                      if request.url.endswith("/v1/responses") else None)
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        first_identity = await self.panel.evaluate(
            "async () => (await chrome.storage.local.get()).savedGroupingsInstallation"
        )
        points, _ = database.scroll(TEST_COLLECTION, with_payload=True)
        self.assertEqual(len(points), 2)
        self.assertEqual(len({point.payload["userId"] for point in points}), 1)
        self.assertIn("userId", database.get_collection(TEST_COLLECTION).payload_schema)

        await self.organize()
        self.assertEqual({group["name"] for group in proposals[-1]["saved_groupings"]}, {"Dev", "Other"})
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        self.assertEqual(database.count(TEST_COLLECTION).count, 2)

        await self.panel.evaluate("() => chrome.storage.local.remove('savedGroupingsInstallation')")
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])
        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        points, _ = database.scroll(TEST_COLLECTION, with_payload=True)
        self.assertEqual(len(points), 4)
        self.assertEqual(len({point.payload["userId"] for point in points}), 2)

        await self.panel.evaluate(
            "identity => chrome.storage.local.set({savedGroupingsInstallation: identity})", first_identity,
        )
        await self.panel.reload()
        await self.organize()
        self.assertEqual(len(proposals[-1]["saved_groupings"]), 2)
        self.assertNotIn("userId", json.dumps(proposals[-1]["saved_groupings"]))
