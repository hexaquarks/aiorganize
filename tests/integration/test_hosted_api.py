import asyncio
import json
import os
import time
import unittest

import boto3
import httpx
import jwt
from playwright.async_api import expect
from qdrant_client import QdrantClient, models

from src.build import COMPILED_EXTENSION
from src.groupings import COLLECTION
from tests.integration.test_panel import PanelTestCase


@unittest.skipUnless(os.environ.get("HOSTED_API_TEST") == "1", "Requires the deployed test stack and test API build")
class HostedApiTest(PanelTestCase):
    extension_path = COMPILED_EXTENSION

    async def test_browser_uses_hosted_api_with_isolation_revocation_and_shared_limits(self):
        aws = boto3.Session(region_name="us-east-1")
        stack = aws.client("cloudformation").describe_stacks(StackName="aiorganize-api-test")["Stacks"][0]
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
        api_url = outputs["ApiUrl"]
        table = aws.resource("dynamodb").Table(outputs["AccessTableName"])
        manifest = await self.panel.evaluate("chrome.runtime.getManifest()")
        self.assertIn(f"{api_url}/*", manifest["host_permissions"])

        database = QdrantClient(
            url=os.environ["QDRANT_ENDPOINT"], api_key=os.environ["QDRANT_API_KEY"],
            timeout=30, check_compatibility=False,
        )
        self.addCleanup(database.close)
        collection = f"{COLLECTION}_test"
        owners = set()

        def cleanup():
            for owner in owners:
                database.delete(collection, models.FilterSelector(filter=models.Filter(must=[
                    models.FieldCondition(key="userId", match=models.MatchValue(value=owner)),
                ])), wait=True)
                table.delete_item(Key={"id": f"revoked:{owner}"})

        self.addCleanup(cleanup)
        await self.install_proposal_fixture()
        proposals = []

        def capture_proposal(request):
            if request.url.endswith("/v1/responses"):
                proposals.append(json.loads(request.post_data_json["input"]))

        self.panel.on("request", capture_proposal)
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])
        first = await self.panel.evaluate("async () => (await chrome.storage.local.get()).savedGroupingsInstallation")
        # The test decodes the identity to target cleanup and operator revocation.
        # The API verifies the signature on every real request.
        owner = jwt.decode(first["token"], options={"verify_signature": False})["sub"]
        owners.add(owner)

        await self.panel.locator("#approve").click()
        await expect(self.panel.locator("#saved-groupings-status")).to_have_text(
            "Approved groupings saved.", timeout=45000,
        )
        await self.organize()
        self.assertEqual({group["name"] for group in proposals[-1]["saved_groupings"]}, {"Dev", "Other"})

        await self.panel.locator("#reject").click()
        await self.panel.evaluate("chrome.storage.local.remove('savedGroupingsInstallation')")
        await self.organize()
        self.assertNotIn("saved_groupings", proposals[-1])
        second = await self.panel.evaluate("async () => (await chrome.storage.local.get()).savedGroupingsInstallation")
        owners.add(jwt.decode(second["token"], options={"verify_signature": False})["sub"])

        async with httpx.AsyncClient(base_url=api_url, timeout=40) as client:
            payload = {"vector": [1.0] + [0.0] * 1535}
            headers = {"Authorization": f"Bearer {first['token']}"}
            window = int(time.time()) // 60
            keys = [f"limit:search:{owner}:{window}", f"limit:search:{owner}:{window + 1}"]
            try:
                for key in keys:
                    table.put_item(Item={"id": key, "hits": 60, "expiresAt": (window + 3) * 60})
                response = await client.post("/v1/groupings/search", headers=headers, json=payload)
                self.assertEqual(response.status_code, 429)
                self.assertIn("retry-after", response.headers)
            finally:
                for key in keys:
                    table.delete_item(Key={"id": key})

            table.put_item(Item={"id": f"revoked:{owner}"})
            await asyncio.sleep(1)
            response = await client.post("/v1/groupings/search", headers=headers, json=payload)
            self.assertEqual(response.status_code, 401)

            await asyncio.sleep(1)
            response = await client.post(
                "/v1/groupings/search", headers={"Authorization": f"Bearer {second['token']}"}, json=payload,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"groups": []})
