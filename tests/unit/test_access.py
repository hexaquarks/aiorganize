import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from moto import mock_aws
from qdrant_client import QdrantClient

from src.access import AccessControl
from src.backend import create_app
from src.groupings import GroupingsStore
from tests.unit.test_backend import SECRET, group


def create_access_table():
    database = boto3.resource("dynamodb", region_name="us-east-1")
    return database.create_table(
        TableName="test-access",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock_aws())
        self.table = create_access_table()
        self.access = AccessControl(self.table)

    def test_limits_survive_new_instances_and_reset_by_window_not_ttl_cleanup(self):
        with patch("src.access.time.time", return_value=120):
            self.access.allow("shared", 2, 60)
            AccessControl(self.table).allow("shared", 2, 60)

            with self.assertRaises(HTTPException) as error:
                AccessControl(self.table).allow("shared", 2, 60)
            self.assertEqual(error.exception.status_code, 429)

        with patch("src.access.time.time", return_value=180):
            AccessControl(self.table).allow("shared", 2, 60)

        self.assertEqual(self.table.scan()["Count"], 2)

    def test_concurrent_requests_cannot_exceed_the_quota(self):
        def attempt(_):
            try:
                self.access.allow("concurrent", 5, 3600)
                return True
            except HTTPException as error:
                self.assertEqual(error.status_code, 429)
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(20))), 5)

    def test_group_batch_cannot_bypass_the_daily_limit(self):
        self.access.allow("groups", 100, 86400, units=99)
        with self.assertRaises(HTTPException):
            self.access.allow("groups", 100, 86400, units=2)

        self.access.allow("groups", 100, 86400, units=1)
        with self.assertRaises(HTTPException):
            self.access.allow("new", 100, 86400, units=101)

    def test_revocation_blocks_reads_and_writes_without_affecting_other_installations(self):
        store = GroupingsStore(QdrantClient(":memory:"), "revocation_test")
        client = self.enterContext(TestClient(create_app(store, SECRET, self.access)))
        first = client.post("/v1/installations").json()["token"]
        second = client.post("/v1/installations").json()["token"]
        headers = {"Authorization": f"Bearer {first}"}
        self.assertEqual(client.post("/v1/groupings", headers=headers, json={"groups": [group()]}).status_code, 200)
        points, _ = store.client.scroll(store.collection)
        owner = points[0].payload["userId"]
        self.table.put_item(Item={"id": f"revoked:{owner}"})

        for path, body in [("/v1/groupings", {"groups": [group()]}),
                           ("/v1/groupings/search", {"vector": group()["vector"]})]:
            self.assertEqual(client.post(path, headers=headers, json=body).status_code, 401)

        response = client.post(
            "/v1/groupings/search", headers={"Authorization": f"Bearer {second}"},
            json={"vector": group()["vector"]},
        )
        self.assertEqual(response.json(), {"groups": []})

    def test_access_storage_failure_is_closed_and_does_not_expose_details(self):
        failure = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "secret"}}, "GetItem")
        with patch.object(self.table, "get_item", side_effect=failure):
            with self.assertRaises(HTTPException) as error:
                self.access.check_installation("owner")

        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret", error.exception.detail)
