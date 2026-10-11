import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

from playwright.async_api import expect

from aiorganize.package_extension import EXTENSION_FILES, PROJECT, build_zip
from tests.integration.test_companion import NativeCompanionTestCase


class PackagedExtensionTest(NativeCompanionTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aiorganize-package-test-")
        self.addCleanup(directory.cleanup)
        self.extension_path = Path(directory.name)
        files = {name: (PROJECT / "extension" / name).read_bytes() for name in EXTENSION_FILES}
        version = json.loads(files["manifest.json"])["version"]
        with ZipFile(io.BytesIO(build_zip(files, f"v{version}", []))) as archive:
            archive.extractall(self.extension_path)
        await super().asyncSetUp()

    async def test_store_package_reads_pages_and_applies_only_after_approval(self):
        manifest = await self.panel.evaluate("() => chrome.runtime.getManifest()")
        self.assertNotIn("debugger", manifest["permissions"])
        self.assertFalse((self.extension_path / "control.html").exists())
        await self.install_native_fixture()
        await self.organize()
        reads = json.loads(self.trace.read_text())
        self.assertTrue(any("pasta" in read.get("content", "") for read in reads))
        await self.assert_no_groups()
        await self.panel.get_by_role("button", name="Reject", exact=True).click()
        await self.assert_no_groups()
        await self.organize()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_have_text("Your tabs are organized.")
        state = await self.worker.evaluate("() => tabGroupState(true)")
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})

    async def test_store_package_reports_missing_companion(self):
        await self.panel.evaluate("""async () => {
            const {panel} = await import('./panel-entry.js');
            const {mountPanel} = await import('./panel.js');
            const {requestProposal} = await import('./proposal-client.js');
            panel.destroy();
            mountPanel(document, request => requestProposal(request, {hostName: 'com.aiorganize.not_installed'}));
        }""")
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("Python companion unavailable")
        await self.assert_no_groups()
