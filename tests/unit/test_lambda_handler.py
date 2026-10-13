import asyncio
import json
import unittest
from unittest.mock import patch

from qdrant_client import QdrantClient
from moto import mock_aws

from src import lambda_handler
from src.groupings import GroupingsStore
from src.access import AccessControl
from tests.unit.test_backend import SECRET, group
from tests.unit.test_access import create_access_table


class LambdaHandlerTest(unittest.TestCase):
    def setUp(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.addCleanup(loop.close)
        self.addCleanup(asyncio.set_event_loop, None)
        self.enterContext(mock_aws())
        access = AccessControl(create_access_table())
        self.enterContext(patch.object(lambda_handler, "access_from_environment", return_value=access))

        self.store = GroupingsStore(QdrantClient(":memory:"), "lambda_test")
        self.addCleanup(self.store.client.close)
        self.enterContext(patch.dict("os.environ", {"APP_SIGNING_SECRET": SECRET}))
        self.factory = self.enterContext(patch.object(lambda_handler, "store_from_environment", return_value=self.store))
        self.initializer = self.enterContext(patch.object(self.store, "initialize", wraps=self.store.initialize))
        lambda_handler.application.cache_clear()
        self.addCleanup(lambda_handler.application.cache_clear)

    def invoke(self, path, body=None, token=None):
        headers = {"content-type": "application/json"}
        if token:
            headers["authorization"] = f"Bearer {token}"

        event = {
            "version": "2.0",
            "rawPath": path,
            "rawQueryString": "",
            "headers": headers,
            "requestContext": {
                "domainName": "example.lambda-url.us-east-1.on.aws",
                "http": {"method": "POST", "path": path, "sourceIp": "192.0.2.1", "protocol": "HTTP/1.1"},
            },
            "body": json.dumps(body or {}),
            "isBase64Encoded": False,
        }
        return lambda_handler.handler(event, None)

    def test_warm_invocations_reuse_client_and_preserve_ownership(self):
        first = json.loads(self.invoke("/v1/installations")["body"])["token"]
        second = json.loads(self.invoke("/v1/installations")["body"])["token"]

        saved = self.invoke("/v1/groupings", {"groups": [group()]}, first)
        self.assertEqual(saved["statusCode"], 200)

        for token, expected_count in [(first, 1), (second, 0)]:
            response = self.invoke("/v1/groupings/search", {"vector": group()["vector"]}, token)
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(len(json.loads(response["body"])["groups"]), expected_count)

        denied = self.invoke("/v1/groupings/search", {"vector": group()["vector"]})
        self.assertEqual(denied["statusCode"], 401)
        self.factory.assert_called_once()
        self.initializer.assert_called_once()

    def test_rate_limit_survives_a_cold_start(self):
        for _ in range(10):
            self.assertEqual(self.invoke("/v1/installations")["statusCode"], 201)

        lambda_handler.application.cache_clear()
        self.assertEqual(self.invoke("/v1/installations")["statusCode"], 429)

    def test_large_requests_are_rejected_before_opening_connections(self):
        response = self.invoke("/v1/groupings", {"padding": "x" * (1024 * 1024)})
        self.assertEqual(response["statusCode"], 413)
        self.factory.assert_not_called()
