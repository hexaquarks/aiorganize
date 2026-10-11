import json
import shlex
import sys
import uuid
from pathlib import Path

from playwright.async_api import expect

from demos.fixtures import CHAT_CONTENT
from demos.extension_chrome import prepare_extension
from tests.integration import test_panel


class NativeCompanionTestCase(test_panel.PanelTestCase):
    async def install_native_fixture(self, *, failure=False):
        host_name = "com.aiorganize.test_" + uuid.uuid4().hex
        origin = self.worker.url.removesuffix("background.js")
        directory = Path(self.profile.name) / "NativeMessagingHosts"
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / f"{host_name}.json"
        self.addCleanup(manifest.unlink, missing_ok=True)
        launcher = Path(self.profile.name) / "fixture.sh"
        self.trace = Path(self.profile.name) / "reads.json"
        project = Path(__file__).resolve().parents[2]
        command = [sys.executable, "-m", "tests.integration.companion_fixture", "--allowed-origin", origin]
        if failure:
            command = [sys.executable, "-c", "raise SystemExit(1)"]
        launcher.write_text(
            "#!/bin/sh\ncd " + shlex.quote(str(project)) + "\n"
            + "export AIORGANIZE_TEST_TRACE=" + shlex.quote(str(self.trace)) + "\n"
            + "exec " + shlex.join(command) + ' "$@"\n'
        )
        launcher.chmod(0o700)
        manifest.write_text(json.dumps({
            "name": host_name, "description": "Temporary integration fixture", "path": str(launcher),
            "type": "stdio", "allowed_origins": [origin],
        }))
        await self.panel.evaluate("""async hostName => {
            const {panel} = await import('./panel-entry.js');
            const {mountPanel} = await import('./panel.js');
            const {requestProposal} = await import('./companion-client.js');
            panel.destroy();
            // The production panel must not need remote debugging to identify or read tabs.
            if (chrome.debugger) {
                chrome.debugger.getTargets = () => { throw new Error('Debugging is unavailable'); };
            }
            mountPanel(document, request => requestProposal(request, {hostName}));
        }""", host_name)


class NativeCompanionTest(NativeCompanionTestCase):
    async def test_native_agent_inspection_rejection_and_approval(self):
        await self.context.new_page()
        other_window = await self.worker.evaluate("() => chrome.windows.create({url: 'about:blank'})")
        await self.install_native_fixture()
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.locator("#preview")).to_be_visible(timeout=20000)
        reads = json.loads(self.trace.read_text())
        self.assertEqual(self.trace.with_suffix(".calls").read_text(), "1")
        self.assertEqual(len(reads), 3)
        self.assertTrue(any(CHAT_CONTENT["cooking"] in read["content"] for read in reads))
        self.assertTrue(any(read["content"] == "" for read in reads))
        await self.assert_no_groups()
        await self.panel.get_by_role("button", name="Reject", exact=True).click()
        await self.assert_no_groups()
        await self.organize()
        await self.panel.get_by_role("button", name="Approve & apply", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_have_text("Your tabs are organized.")
        state = await self.worker.evaluate("() => tabGroupState(true)")
        self.assertEqual({group["name"] for group in state["groups"]}, {"Dev", "Other"})
        other_tabs = [tab for tab in state["tabs"] if tab["window_id"] == other_window["id"]]
        self.assertEqual(len(other_tabs), 1)
        self.assertEqual(other_tabs[0]["group_id"], -1)

    async def test_native_host_failure_leaves_tabs_unchanged(self):
        await self.install_native_fixture(failure=True)
        await self.panel.get_by_role("button", name="Organize tabs", exact=True).click()
        await expect(self.panel.get_by_role("status")).to_contain_text("Python companion unavailable")
        await expect(self.panel.locator("#approve")).to_be_disabled()
        await self.assert_no_groups()

    async def test_launcher_registers_a_working_companion_for_its_profile(self):
        manifest = await prepare_extension(self.context, Path(self.profile.name))
        config = json.loads(manifest.read_text())
        self.assertEqual(config["allowed_origins"], [self.worker.url.removesuffix("background.js")])
        # Loading updated extension code closes its old pages; open a fresh panel after setup.
        self.panel = await self.context.new_page()
        await self.panel.goto(config["allowed_origins"][0] + "panel.html")
        # An invalid request proves the real launcher is reachable without making an LLM call.
        response = await self.panel.evaluate("""() => chrome.runtime.sendNativeMessage(
            'com.aiorganize.companion', {type: 'organize', window_id: 1, snapshot: []}
        )""")
        self.assertEqual(response["type"], "error")
        state = await self.panel.evaluate("() => tabGroupState(true)")
        self.assertEqual(state["groups"], [])

    async def test_cancelling_a_request_disconnects_its_native_port(self):
        result = await self.panel.evaluate("""async () => {
            const {requestProposal} = await import('./companion-client.js');
            const original = chrome.runtime.connectNative;
            let disconnected = 0;
            chrome.runtime.connectNative = () => ({
                onMessage: {addListener() {}},
                onDisconnect: {addListener() {}},
                postMessage() {},
                disconnect() { disconnected += 1; },
            });
            try {
                const controller = new AbortController();
                const request = requestProposal({snapshot: [], window_id: 1, signal: controller.signal});
                controller.abort();
                const error = await request.catch(error => error.name);
                return {error, disconnected};
            } finally {
                chrome.runtime.connectNative = original;
            }
        }""")
        self.assertEqual(result, {"error": "AbortError", "disconnected": 1})
        await self.assert_no_groups()
