import asyncio
import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

from playwright.async_api import expect

from src.build import COMPILED_EXTENSION, EXTENSION_FILES, PROJECT, build_zip
from tests.integration.test_panel import PanelTestCase
from tests.fixtures import PRIVATE_PAGE_TEXT, TAB_STATE


class BrowserApiTest(PanelTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.requests = []

    async def save_key(self, *, remember=False):
        await self.connect(remember=remember, api_key="test-key")
        await self.panel.unroute("https://api.openai.com/v1/responses")

    async def install_api_fixture(self, *, status=200, invalid=False, delayed=False):
        self.request_started = asyncio.Event()
        self.finish_request = asyncio.Event()
        self.request_finished = asyncio.Event()

        async def respond(route):
            request = route.request.post_data_json
            self.requests.append(request)
            self.assertEqual(route.request.headers["authorization"], "Bearer test-key")
            context = json.loads(request["input"])
            tabs = context["tabs"]
            proposal = {
                "groups": [
                    {"name": "Dev", "tab_ids": [tab["id"] for tab in tabs[:2]]},
                    {"name": "Other", "tab_ids": [tab["id"] for tab in tabs[2:]]},
                ]
            }
            if invalid:
                proposal["groups"][0]["tab_ids"].append(tabs[2]["id"])
            if delayed:
                self.request_started.set()
                await self.finish_request.wait()
            await route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(proposal)}]}
                        ],
                        "error": {"message": "sensitive-provider-detail"},
                    }
                ),
            )
            self.request_finished.set()

        await self.panel.route("https://api.openai.com/v1/responses", respond)

    async def test_minimal_permissions_and_missing_key_changes_no_tabs(self):
        manifest = await self.panel.evaluate("() => chrome.runtime.getManifest()")
        self.assertNotIn("debugger", manifest["permissions"])
        self.assertNotIn("nativeMessaging", manifest["permissions"])
        self.assertNotIn("scripting", manifest["permissions"])
        self.assertEqual(manifest["host_permissions"], ["https://api.openai.com/*", "https://*.cloud.qdrant.io/*"])
        self.assertFalse((self.extension_path / "control.html").exists())
        self.assertFalse((self.extension_path / "companion-client.js").exists())
        self.assertFalse((self.extension_path / "page-reader.js").exists())
        await expect(self.panel.locator("#organize")).to_be_disabled()

        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option")).to_have_count(15)
        await expect(self.panel.get_by_role("option", name="GPT-6.1 Sol", exact=True)).to_have_count(1)

        await self.panel.keyboard.press("Escape")

        await self.assert_no_groups()

    async def test_browser_request_uses_only_metadata_and_applies_only_after_approval(self):
        await self.save_key()
        await self.install_api_fixture()
        await self.organize()
        request = self.requests[0]
        self.assertFalse(request["store"])
        self.assertEqual(request["model"], "gpt-6.1-sol")
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        context = json.loads(request["input"])
        self.assertEqual(len(context["tabs"]), 6)
        self.assertEqual(set(context), {"tabs"})
        for tab in context["tabs"]:
            self.assertEqual(set(tab), {"id", "title", "url"})
        self.assertNotIn("test-key", json.dumps(request))
        self.assertNotIn(PRIVATE_PAGE_TEXT, json.dumps(request))
        await self.assert_no_groups()

        await self.panel.get_by_role("button", name="Reject", exact=True).click()

        await self.assert_no_groups()

        await self.organize()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()

        await expect(self.panel.locator("#status")).to_have_text("Your tabs are organized.")
        state = await self.panel.evaluate(TAB_STATE)
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})

    async def test_invalid_proposal_and_provider_error_are_safe(self):
        await self.save_key()
        await self.install_api_fixture(invalid=True)
        await self.panel.locator("#organize").click()

        await expect(self.panel.locator("#status")).to_contain_text("duplicate")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

        await self.panel.unroute("https://api.openai.com/v1/responses")
        await self.install_api_fixture(status=401)
        await self.panel.locator("#organize").click()

        await expect(self.panel.locator("#status")).to_contain_text("Key rejected")
        self.assertNotIn("sensitive-provider-detail", await self.panel.locator("body").inner_text())
        await self.assert_no_groups()

    async def test_key_storage_is_optional_local_and_can_be_removed(self):
        await self.save_key()

        self.assertEqual(await self.panel.locator("#api-key").input_value(), "")
        stored = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(null),
            session: await chrome.storage.session.get(null),
            sync: await chrome.storage.sync.get(null),
        })""")
        self.assertNotIn("connection", stored["local"])
        self.assertEqual(stored["session"]["connection"]["apiKey"], "test-key")
        self.assertEqual(stored["sync"], {})

        await self.panel.locator("#edit-connection").click()
        await self.save_key(remember=True)
        await self.panel.evaluate("() => chrome.storage.session.clear()")
        await self.panel.reload()

        await expect(self.panel.locator("#ready")).to_be_visible()

        await self.panel.locator("#edit-connection").click()

        await expect(self.panel.locator("#remember-key")).to_be_checked()

        await self.panel.locator("#forget-key").click()

        self.assertEqual(
            await self.panel.evaluate("""async () => {
            return (await chrome.storage.session.get("connection")).connection?.apiKey || "";
        }"""),
            "",
        )

    async def test_aborted_browser_request_does_not_create_a_preview(self):
        await self.save_key()
        await self.install_api_fixture(delayed=True)
        await self.panel.locator("#organize").click()

        await expect(self.panel.locator("#organize")).to_be_disabled()
        await asyncio.wait_for(self.request_started.wait(), timeout=10)
        await self.panel.evaluate("""async () => {
            window.dispatchEvent(new Event("pagehide"));
        }""")
        self.finish_request.set()
        await asyncio.wait_for(self.request_finished.wait(), timeout=10)
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await self.assert_no_groups()


class PackagedBrowserApiTest(BrowserApiTest):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aiorganize-package-test-")
        self.addCleanup(directory.cleanup)
        self.extension_path = Path(directory.name)
        files = {name: (COMPILED_EXTENSION / name).read_bytes() for name in EXTENSION_FILES}
        version = json.loads(files["manifest.json"])["version"]
        with ZipFile(io.BytesIO(build_zip(files, f"v{version}", []))) as archive:
            archive.extractall(self.extension_path)
        await super().asyncSetUp()
