import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs

from src import webstore
from src.build import EXTENSION_FILES, PROJECT
from src.webstore import WebStoreClient, release, store_versions


PRIVATE_STATUS = {
    "publishedItemRevisionStatus": {
        "state": "PUBLISHED_TO_TESTERS", "distributionChannels": [{"crxVersion": "0.0.9"}],
    },
}


class WebStoreTest(unittest.TestCase):
    def setUp(self):
        self.files = {name: (PROJECT / "extension" / name).read_bytes() for name in EXTENSION_FILES}
        manifest = json.loads(self.files["manifest.json"])
        manifest["version"] = "0.1.0"
        self.files["manifest.json"] = json.dumps(manifest).encode()
        self.client = Mock(spec=WebStoreClient)
        self.client.status.return_value = PRIVATE_STATUS
        self.client.publish_private.return_value = {"state": "PENDING_REVIEW"}
        self.read_files = patch.object(webstore, "tagged_files", return_value=self.files)
        self.read_files.start()
        self.addCleanup(self.read_files.stop)
        self.read_tags = patch.object(webstore, "git", return_value=b"v0.0.9\nv0.1.0\n")
        self.read_tags.start()
        self.addCleanup(self.read_tags.stop)

    def test_upload_does_not_publish_by_default(self):
        release(self.client, "v0.1.0", publish_private=False, owner_only_confirmed=False)
        self.client.upload.assert_called_once()
        self.client.publish_private.assert_not_called()

    def test_private_update_is_uploaded_before_submission(self):
        release(self.client, "v0.1.0", publish_private=True, owner_only_confirmed=True)
        self.assertEqual([call[0] for call in self.client.mock_calls], ["status", "upload", "publish_private"])

    def test_public_unpublished_or_unconfirmed_items_cannot_be_published(self):
        for state in ("PUBLISHED", None, "STAGED"):
            self.client.reset_mock()
            self.client.status.return_value = {
                "publishedItemRevisionStatus": {
                    "state": state, "distributionChannels": [{"crxVersion": "0.0.9"}],
                },
            }
            with self.subTest(state=state), self.assertRaises(ValueError):
                release(self.client, "v0.1.0", publish_private=True, owner_only_confirmed=True)
            self.client.upload.assert_not_called()
            self.client.publish_private.assert_not_called()
        with self.assertRaises(ValueError):
            release(self.client, "v0.1.0", publish_private=True, owner_only_confirmed=False)

    def test_old_versions_and_active_submissions_are_blocked_before_upload(self):
        for status in (
            {"publishedItemRevisionStatus": {
                "state": "PUBLISHED_TO_TESTERS", "distributionChannels": [{"crxVersion": "0.1"}],
            }},
            {**PRIVATE_STATUS, "submittedItemRevisionStatus": {"state": "PENDING_REVIEW"}},
            {**PRIVATE_STATUS, "submittedItemRevisionStatus": {"state": "STAGED"}},
            {**PRIVATE_STATUS, "lastAsyncUploadState": "IN_PROGRESS"},
            {**PRIVATE_STATUS, "warned": True},
        ):
            self.client.status.return_value = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                release(self.client, "v0.1.0", publish_private=False, owner_only_confirmed=False)
            self.client.upload.assert_not_called()

    def test_failed_upload_prevents_submission(self):
        self.client.upload.side_effect = ValueError("Upload failed")
        with self.assertRaises(ValueError):
            release(self.client, "v0.1.0", publish_private=True, owner_only_confirmed=True)
        self.client.publish_private.assert_not_called()

    def test_version_disclosure_is_required_for_existing_revisions(self):
        self.assertEqual(store_versions(PRIVATE_STATUS), ["0.0.9"])
        self.assertEqual(store_versions({}), [])
        with self.assertRaises(ValueError):
            store_versions({"publishedItemRevisionStatus": {"state": "PUBLISHED_TO_TESTERS"}})

    def test_oauth_and_v2_requests_use_correct_endpoints_without_printing_secrets(self):
        environment = {
            "CWS_PUBLISHER_ID": "publisher-123", "CWS_EXTENSION_ID": "a" * 32,
            "CWS_CLIENT_ID": "test-client", "CWS_CLIENT_SECRET": "test-secret",
            "CWS_REFRESH_TOKEN": "test-refresh",
        }
        with patch.dict(webstore.os.environ, environment, clear=True):
            with patch.object(webstore, "_request_json", side_effect=[
                {"access_token": "test-token"}, PRIVATE_STATUS,
                {"uploadState": "SUCCEEDED"}, {"state": "PENDING_REVIEW"},
            ]) as request:
                with patch("sys.stdout", new=io.StringIO()) as output:
                    client = WebStoreClient()
                    client.status()
                    client.upload(b"ZIP")
                    client.publish_private()
                token, status, upload, publish = [call.args[0] for call in request.call_args_list]
                self.assertEqual(token.full_url, "https://oauth2.googleapis.com/token")
                self.assertEqual(parse_qs(token.data.decode())["refresh_token"], ["test-refresh"])
                self.assertTrue(status.full_url.endswith(f"/v2/publishers/publisher-123/items/{'a' * 32}:fetchStatus"))
                self.assertEqual(status.get_method(), "GET")
                self.assertIn("/upload/v2/", upload.full_url)
                self.assertEqual(upload.data, b"ZIP")
                self.assertEqual(upload.get_header("Authorization"), "Bearer test-token")
                self.assertEqual(json.loads(publish.data), {
                    "publishType": "DEFAULT_PUBLISH", "skipReview": False, "blockOnWarnings": True,
                })
                self.assertEqual(output.getvalue(), "")

    def test_async_upload_is_polled_and_failure_or_timeout_is_not_success(self):
        client = object.__new__(WebStoreClient)
        client._request = Mock(return_value={"uploadState": "IN_PROGRESS"})
        client.status = Mock(return_value={"lastAsyncUploadState": "SUCCEEDED"})
        with patch.object(webstore.time, "sleep"):
            client.upload(b"ZIP")
        client.status.assert_called_once()
        client.status.return_value = {"lastAsyncUploadState": "FAILED"}
        with patch.object(webstore.time, "sleep"), self.assertRaises(ValueError):
            client.upload(b"ZIP")
        client.status.reset_mock()
        with self.assertRaises(ValueError):
            client.upload(b"ZIP", wait_seconds=0)
        client.status.assert_not_called()

    def test_missing_credentials_and_http_errors_do_not_expose_secrets(self):
        with patch.dict(webstore.os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "CWS_PUBLISHER_ID"):
            WebStoreClient()
        error = HTTPError(webstore.TOKEN_URL, 400, "test-secret", {}, io.BytesIO(b"test-refresh"))
        with patch.object(webstore, "urlopen", side_effect=error):
            with self.assertRaises(ValueError) as raised:
                webstore._request_json(webstore.Request(webstore.TOKEN_URL))
        self.assertNotIn("test-secret", str(raised.exception))
        self.assertNotIn("test-refresh", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
