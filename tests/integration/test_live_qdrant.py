import json
import os
import unittest
from urllib.parse import urlparse

from playwright.async_api import expect

from src.build import PROJECT
from tests.fixtures import TAB_STATE
from tests.integration.test_panel import PanelTestCase


TEST_COLLECTION = "aiorganize_groups_v1_text_embedding_3_small_1536_test"


@unittest.skipUnless(os.environ.get("QDRANT_LIVE_TEST") == "1", "Run make test-qdrant for the live database test")
class LiveQdrantTest(PanelTestCase):
    extension_path = PROJECT / "dist" / "qdrant-test"

    async def database_request(self, method, suffix="", body=None):
        # Keep credentials inside the extension and constrain every test operation to its collection.
        return await self.panel.evaluate("""async ({method, suffix, body, collection}) => {
            const {qdrant} = await chrome.storage.session.get('qdrant');
            const response = await fetch(`${qdrant.url}/collections/${collection}${suffix}`, {
                method,
                headers: {'api-key': qdrant.apiKey, 'Content-Type': 'application/json'},
                body: body === null ? undefined : JSON.stringify(body),
            });
            return {status: response.status, body: await response.json()};
        }""", {"method": method, "suffix": suffix, "body": body, "collection": TEST_COLLECTION})

    async def test_approval_save_search_and_reuse_with_real_qdrant(self):
        verified = await self.panel.evaluate("""async () => {
            const {qdrant} = await chrome.storage.session.get('qdrant');
            return Boolean(qdrant?.verifiedAt);
        }""")
        self.assertTrue(verified, "Live Qdrant connection could not be verified from .env")

        unexpected_collections = []

        async def protect_user_collection(route):
            path = urlparse(route.request.url).path
            collection_path = f"/collections/{TEST_COLLECTION}"
            if path != collection_path and not path.startswith(f"{collection_path}/"):
                unexpected_collections.append(path)
                await route.abort()
                return
            await route.continue_()

        await self.panel.route("**/collections/**", protect_user_collection)
        reset = await self.database_request("DELETE")
        self.assertIn(reset["status"], (200, 404))

        async def clear_test_points():
            cleared = await self.database_request("POST", "/points/delete?wait=true", {"filter": {}})
            self.assertIn(cleared["status"], (200, 404))

            if cleared["status"] == 200:
                count = await self.database_request("POST", "/points/count", {"exact": True})
                self.assertEqual(count["body"]["result"]["count"], 0)

        self.addAsyncCleanup(clear_test_points)
        await self.install_proposal_fixture()
        proposal_inputs = []

        def record_proposal(request):
            if request.url == "https://api.openai.com/v1/responses":
                proposal_inputs.append(json.loads(request.post_data_json["input"]))

        self.panel.on("request", record_proposal)

        async def embed(route):
            inputs = route.request.post_data_json["input"]
            vectors = []
            for index, text in enumerate(inputs):
                # Two orthogonal vectors let the real database rank Dev ahead of Other.
                other = json.loads(text).get("name") == "Other"
                vector = [0, 1] if other else [1, 0]
                vectors.append({"index": index, "embedding": vector + [0] * 1534})
            await route.fulfill(json={"model": "text-embedding-3-small", "data": vectors})

        await self.panel.route("https://api.openai.com/v1/embeddings", embed)
        await self.organize()
        self.assertNotIn("saved_groupings", proposal_inputs[-1])
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )

        collection = await self.database_request("GET")
        self.assertEqual(collection["status"], 200)
        result = collection["body"]["result"]
        self.assertEqual(result["config"]["params"]["vectors"], {"size": 1536, "distance": "Cosine"})
        self.assertTrue(
            {"userId", "schemaVersion", "embeddingModel", "embeddingDimensions"} <= result["payload_schema"].keys()
        )

        saved = await self.database_request("POST", "/points/scroll", {"limit": 10, "with_payload": True})
        points = saved["body"]["result"]["points"]
        self.assertEqual({point["payload"]["name"] for point in points}, {"Dev", "Other"})
        self.assertEqual(len(points), 2)
        user_a = await self.panel.evaluate(
            "async () => (await chrome.storage.local.get('savedGroupingsUserId')).savedGroupingsUserId"
        )
        self.assertTrue(all(point["payload"]["userId"] == user_a for point in points))
        original_ids = {point["id"] for point in points}
        applied = await self.panel.evaluate(TAB_STATE)

        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#preview")).to_be_visible(timeout=45000)
        examples = proposal_inputs[-1]["saved_groupings"]
        self.assertEqual([example["name"] for example in examples], ["Dev", "Other"])
        by_name = {point["payload"]["name"]: point["payload"]["pages"] for point in points}
        self.assertEqual(examples, [{"name": name, "pages": by_name[name]} for name in ("Dev", "Other")])
        self.assertNotIn("userId", json.dumps(examples))
        self.assertEqual(await self.panel.evaluate(TAB_STATE), applied)

        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        saved_again = await self.database_request("POST", "/points/scroll", {"limit": 10})
        repeated_points = saved_again["body"]["result"]["points"]
        self.assertEqual(len(repeated_points), 2)
        self.assertEqual({point["id"] for point in repeated_points}, original_ids)

        # The same shared collection must not expose User A's groups to User B.
        user_b = "e8bbb44b-3c47-4d79-9647-dfe3d547989c"
        await self.panel.evaluate(
            "userId => chrome.storage.local.set({savedGroupingsUserId: userId})", user_b,
        )
        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#preview")).to_be_visible(timeout=45000)
        self.assertNotIn("saved_groupings", proposal_inputs[-1])
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        both_users = await self.database_request("POST", "/points/scroll", {"limit": 10, "with_payload": True})
        all_points = both_users["body"]["result"]["points"]
        self.assertEqual(len(all_points), 4)
        self.assertEqual({point["payload"]["userId"] for point in all_points}, {user_a, user_b})

        # Make B's stored history recognizable, while keeping its vectors equally relevant.
        b_points = [point for point in all_points if point["payload"]["userId"] == user_b]
        for point in b_points:
            payload = {**point["payload"], "name": "BOnly"}
            updated = await self.database_request("POST", "/points/payload?wait=true", {
                "points": [point["id"]], "payload": payload,
            })
            self.assertEqual(updated["status"], 200)

        await self.panel.evaluate(
            "userId => chrome.storage.local.set({savedGroupingsUserId: userId})", user_a,
        )
        await self.panel.reload()
        await expect(self.panel.locator("#ready")).to_be_visible()
        persisted_user = await self.panel.evaluate(
            "async () => (await chrome.storage.local.get('savedGroupingsUserId')).savedGroupingsUserId"
        )
        self.assertEqual(persisted_user, user_a)
        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#preview")).to_be_visible(timeout=45000)
        self.assertEqual(proposal_inputs[-1]["saved_groupings"], examples)
        self.assertNotIn("BOnly", json.dumps(proposal_inputs[-1]))

        await self.panel.locator("#reject").click()

        await self.panel.evaluate(
            "userId => chrome.storage.local.set({savedGroupingsUserId: userId})", user_b,
        )
        await self.panel.locator("#organize").click()
        await expect(self.panel.locator("#preview")).to_be_visible(timeout=45000)
        self.assertEqual(
            [example["name"] for example in proposal_inputs[-1]["saved_groupings"]], ["BOnly", "BOnly"],
        )
        self.assertEqual(unexpected_collections, [])
