import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from src.api import create_app
from src.groupings import GroupingsStore

SECRET = "test-signing-secret-that-is-at-least-thirty-two-bytes"


def group(name="Dev"):
    return {
        "name": name,
        "pages": [{"title": "Python", "url": "https://python.org"}],
        "approvedAt": "2026-10-13T12:00:00Z",
        "vector": [1.0] + [0.0] * 1535,
    }


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.database = QdrantClient(":memory:")
        self.store = GroupingsStore(self.database, "saved_groupings_test")
        self.client = self.enterContext(TestClient(create_app(self.store, SECRET)))

    def installation(self):
        response = self.client.post("/v1/installations")
        self.assertEqual(response.status_code, 201)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_server_owns_identity_and_isolates_reads_and_idempotent_writes(self):
        first, second = self.installation(), self.installation()
        payload = {"groups": [group()]}
        saved = self.client.post("/v1/groupings", headers=first, json=payload)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.post("/v1/groupings", headers=first, json=payload).json(), saved.json())
        other = self.client.post("/v1/groupings", headers=second, json={"groups": [group("Other")]})
        self.assertNotEqual(other.json(), saved.json())
        for headers, name in [(first, "Dev"), (second, "Other")]:
            found = self.client.post("/v1/groupings/search", headers=headers, json={"vector": group()["vector"]})
            self.assertEqual(found.status_code, 200)
            self.assertEqual([item["name"] for item in found.json()["groups"]], [name])
            self.assertEqual(set(found.json()["groups"][0]), {"name", "pages"})
        self.assertEqual(self.database.count("saved_groupings_test").count, 2)

    def test_client_cannot_choose_owner_collection_or_record_ids(self):
        headers = self.installation()
        for field in ("userId", "collection", "id"):
            response = self.client.post("/v1/groupings", headers=headers, json={"groups": [group()], field: "victim"})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.database.count("saved_groupings_test").count, 0)

    def test_missing_or_forged_credentials_never_reach_storage(self):
        forged = jwt.encode({"sub": "victim", "iss": "aiorganize", "aud": "saved-groupings", "iat": 1}, "x" * 32)
        for headers in ({}, {"Authorization": "Bearer broken"}, {"Authorization": f"Bearer {forged}"}):
            response = self.client.post("/v1/groupings", headers=headers, json={"groups": [group()]})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.database.count("saved_groupings_test").count, 0)

    def test_invalid_vectors_and_payloads_are_rejected_without_echoing_inputs(self):
        headers = self.installation()
        for vector in ([1], [0] * 1536, ["provider-secret"] * 1536):
            response = self.client.post("/v1/groupings/search", headers=headers, json={"vector": vector})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("provider-secret", response.text)
        response = self.client.post("/v1/groupings", headers=headers, json={"groups": [group("")]})
        self.assertEqual(response.status_code, 422)

    def test_legacy_unowned_records_are_not_claimed(self):
        from uuid import uuid4

        from qdrant_client.models import PointStruct

        self.database.upsert("saved_groupings_test", [PointStruct(
            id=str(uuid4()), vector=group()["vector"], payload={"name": "Legacy", "pages": group()["pages"]},
        )])
        response = self.client.post(
            "/v1/groupings/search", headers=self.installation(), json={"vector": group()["vector"]},
        )
        self.assertEqual(response.json(), {"groups": []})

    def test_signing_secret_is_required(self):
        with self.assertRaises(ValueError):
            create_app(self.store, "")

    def test_app_instances_keep_separate_databases_and_signing_secrets(self):
        other_store = GroupingsStore(QdrantClient(":memory:"), "other_installations_test")
        other_secret = "another-independent-signing-secret-for-tests"
        first = self.installation()

        with TestClient(create_app(other_store, other_secret)) as other_client:
            response = other_client.post("/v1/installations")
            second = {"Authorization": f"Bearer {response.json()['token']}"}
            payload = {"groups": [group()]}

            self.assertEqual(other_client.post("/v1/groupings", headers=first, json=payload).status_code, 401)
            self.assertEqual(self.client.post("/v1/groupings", headers=second, json=payload).status_code, 401)
            self.assertEqual(other_client.post("/v1/groupings", headers=second, json=payload).status_code, 200)
            self.assertEqual(other_store.client.count("other_installations_test").count, 1)
            self.assertEqual(self.database.count("saved_groupings_test").count, 0)

    def test_database_errors_do_not_expose_provider_details(self):
        headers = self.installation()

        with patch.object(self.store, "save", side_effect=RuntimeError("private-provider-secret")):
            response = self.client.post("/v1/groupings", headers=headers, json={"groups": [group()]})

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-provider-secret", response.text)

    def test_startup_fails_when_database_cannot_connect(self):
        with (
            patch.object(self.store, "initialize", side_effect=RuntimeError("Database unavailable")),
            self.assertRaisesRegex(RuntimeError, "Database unavailable"),
            TestClient(create_app(self.store, SECRET)),
        ):
            self.fail("The API must not start without its database.")
