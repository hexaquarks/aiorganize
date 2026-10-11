import asyncio
import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

from playwright.async_api import expect

from aiorganize.package_extension import EXTENSION_FILES, PROJECT, build_zip
from tests.integration.test_panel import PanelTestCase


class PackagedExtensionTest(PanelTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aiorganize-package-test-")
        self.addCleanup(directory.cleanup)
        self.extension_path = Path(directory.name)
        files = {name: (PROJECT / "extension" / name).read_bytes() for name in EXTENSION_FILES}
        version = json.loads(files["manifest.json"])["version"]
        with ZipFile(io.BytesIO(build_zip(files, f"v{version}", []))) as archive:
            archive.extractall(self.extension_path)
        await super().asyncSetUp()
        self.requests = []

    async def save_key(self, *, remember=False):
        await self.panel.locator("#settings summary").click()
        await self.panel.locator("#api-key").fill("test-key")
        await self.panel.locator("#remember-key").set_checked(remember)
        await self.panel.get_by_role("button", name="Save settings", exact=True).click()
        await expect(self.panel.locator("#settings-status")).to_contain_text("Key saved")

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
            proposal = {"groups": [
                {"name": "Dev", "tab_ids": [tab["id"] for tab in tabs[:2]]},
                {"name": "Other", "tab_ids": [tab["id"] for tab in tabs[2:]]},
            ]}
            if invalid:
                proposal["groups"][0]["tab_ids"].append(tabs[2]["id"])
            if delayed:
                self.request_started.set()
                await self.finish_request.wait()
            await route.fulfill(status=status, content_type="application/json", body=json.dumps({
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(proposal)}]}],
                "error": {"message": "sensitive-provider-detail"},
            }))
            self.request_finished.set()

        await self.panel.route("https://api.openai.com/v1/responses", respond)

    async def test_release_has_no_companion_and_missing_key_changes_no_tabs(self):
        manifest = await self.panel.evaluate("() => chrome.runtime.getManifest()")
        self.assertNotIn("debugger", manifest["permissions"])
        self.assertNotIn("nativeMessaging", manifest["permissions"])
        self.assertFalse((self.extension_path / "control.html").exists())
        self.assertFalse((self.extension_path / "companion-client.js").exists())
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("Add your OpenAI API key")
        await self.assert_no_groups()

    async def test_browser_request_inspects_pages_and_applies_only_after_approval(self):
        await self.save_key()
        await self.install_api_fixture()
        await self.organize()
        request = self.requests[0]
        self.assertFalse(request["store"])
        self.assertEqual(request["model"], "gpt-4.1-mini")
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        context = json.loads(request["input"])
        self.assertEqual(len(context["tabs"]), 6)
        self.assertEqual(len(context["page_reads"]), 2)
        self.assertTrue(any("pasta" in read["content"] for read in context["page_reads"]))
        self.assertNotIn("test-key", json.dumps(request))
        await self.assert_no_groups()
        await self.panel.get_by_role("button", name="Reject", exact=True).click()
        await self.assert_no_groups()
        await self.organize()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_have_text("Your tabs are organized.")
        state = await self.worker.evaluate("() => tabGroupState(true)")
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})

    async def test_invalid_proposal_and_provider_error_are_safe(self):
        await self.save_key()
        await self.install_api_fixture(invalid=True)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("duplicate")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()
        await self.panel.unroute("https://api.openai.com/v1/responses")
        await self.install_api_fixture(status=401)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("rejected the API key")
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
        self.assertNotIn("apiKey", stored["local"])
        self.assertEqual(stored["session"]["apiKey"], "test-key")
        self.assertEqual(stored["sync"], {})
        await self.panel.locator("#remember-key").check()
        await self.panel.get_by_role("button", name="Save settings", exact=True).click()
        await expect(self.panel.locator("#settings-status")).to_have_text("Key saved on this device.")
        page_key = await self.panel.evaluate("""async () => {
            const tab = (await tabGroupState(true)).tabs[0];
            const [result] = await chrome.scripting.executeScript({
                target: {tabId: tab.chrome_id},
                func: async () => {
                    try { return (await chrome.storage.local.get('apiKey')).apiKey || null; }
                    catch { return null; }
                },
            });
            return result.result;
        }""")
        self.assertIsNone(page_key, "Page scripts must not read the stored API key")
        await self.panel.evaluate("() => chrome.storage.session.clear()")
        await self.panel.reload()
        await self.panel.locator("#settings summary").click()
        await expect(self.panel.locator("#remember-key")).to_be_checked()
        self.assertEqual(await self.panel.locator("#api-key").input_value(), "")
        await self.panel.get_by_role("button", name="Forget key", exact=True).click()
        await expect(self.panel.locator("#settings-status")).to_have_text("API key removed.")
        self.assertEqual(await self.panel.evaluate("""async () => {
            const {getSettings} = await import('./settings.js');
            return (await getSettings()).apiKey;
        }"""), "")

    async def test_aborted_browser_request_does_not_create_a_preview(self):
        await self.save_key()
        await self.install_api_fixture(delayed=True)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.locator("#organize")).to_be_disabled()
        await asyncio.wait_for(self.request_started.wait(), timeout=10)
        await self.panel.evaluate("""async () => {
            const {panel} = await import('./panel-entry.js');
            panel.destroy();
        }""")
        self.finish_request.set()
        await asyncio.wait_for(self.request_finished.wait(), timeout=10)
        await expect(self.panel.locator("#preview")).to_be_hidden()
        await self.assert_no_groups()
