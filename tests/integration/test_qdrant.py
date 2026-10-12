import asyncio
import json

from playwright.async_api import expect

from tests.integration import test_settings
from tests.integration.test_panel import PanelTestCase


class QdrantConnectionTest(PanelTestCase):
    reopen_browser = test_settings.ConnectionSetupTest.reopen_browser

    async def fill_qdrant(self, *, remember=False):
        await self.panel.locator("#qdrant-url").fill("https://test.cloud.qdrant.io:6333/")
        await self.panel.locator("#qdrant-key").fill("qdrant-test-secret")
        await self.panel.locator("#qdrant-remember").set_checked(remember)

    async def stores(self):
        return await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")

    async def test_read_only_verification_and_disconnect_leave_openai_usable(self):
        requests = []

        async def respond(route):
            requests.append(route.request)
            await route.fulfill(json={"status": "ok", "result": {"collections": []}})

        await self.panel.route("https://test.cloud.qdrant.io:6333/**", respond)
        await self.fill_qdrant()
        await self.panel.set_viewport_size({"width": 360, "height": 800})
        await self.panel.screenshot(path="dist/qdrant-settings-preview.png", full_page=True)
        self.assertTrue(await self.panel.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
        await self.panel.get_by_role("button", name="Show Qdrant key").click()
        await expect(self.panel.locator("#qdrant-key")).to_have_attribute("type", "text")
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("verified and saved")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.url, "https://test.cloud.qdrant.io:6333/collections")
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.post_data)
        self.assertEqual(request.headers["api-key"], "qdrant-test-secret")
        stores = await self.stores()
        self.assertNotIn("qdrant", stores["local"])
        self.assertEqual(stores["session"]["qdrant"]["url"], "https://test.cloud.qdrant.io:6333")
        await self.panel.reload()
        await expect(self.panel.locator("#qdrant-saved")).to_contain_text("Session only")
        await expect(self.panel.locator("#qdrant-key")).to_have_attribute("type", "password")
        await self.connect()
        await expect(self.panel.locator("#qdrant-summary")).to_contain_text("Qdrant connected")
        await self.panel.locator("#settings-toggle").click()
        before = await self.read_settings()
        await self.panel.locator("#qdrant-disconnect").click()
        await expect(self.panel.locator("#qdrant-saved")).to_have_count(0)
        self.assertEqual(await self.read_settings(), before)
        self.assertNotIn("qdrant-test-secret", json.dumps(await self.stores()))
        await self.panel.locator("#cancel-settings").click()
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_persistence_choices_and_browser_restart(self):
        await self.panel.route("https://test.cloud.qdrant.io:6333/**", lambda route: route.fulfill(
            json={"status": "ok", "result": {"collections": [{"name": "existing"}]}},
        ))
        await self.fill_qdrant(remember=True)
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-saved")).to_contain_text("Remembered")
        await self.reopen_browser()
        await expect(self.panel.locator("#qdrant-saved")).to_contain_text("Remembered")
        await self.panel.route("https://test.cloud.qdrant.io:6333/**", lambda route: route.fulfill(
            json={"status": "ok", "result": {"collections": []}},
        ))
        await self.panel.locator("#qdrant-remember").uncheck()
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-saved")).to_contain_text("Session only")
        self.assertNotIn("qdrant", (await self.stores())["local"])
        await self.reopen_browser()
        await expect(self.panel.locator("#qdrant-key")).to_be_empty()
        self.assertNotIn("qdrant", (await self.stores())["session"])

    async def test_failures_preserve_saved_connection_and_hide_provider_messages(self):
        endpoint = "https://test.cloud.qdrant.io:6333/**"
        await self.panel.route(endpoint, lambda route: route.fulfill(
            json={"status": "ok", "result": {"collections": []}},
        ))
        await self.fill_qdrant()
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("verified")
        before = await self.stores()
        await self.panel.locator("#qdrant-key").fill("replacement-secret")
        for status, body, message in [
            (401, {"status": "secret"}, "Key rejected"),
            (403, {}, "Key rejected"),
            (404, {}, "endpoint not found"),
            (429, {}, "busy"),
            (503, {}, "unavailable"),
            (200, {"status": "ok", "result": {"collections": [None]}}, "invalid response"),
        ]:
            await self.panel.unroute(endpoint)
            async def respond(route, *, status=status, body=body):
                await route.fulfill(status=status, json=body)

            await self.panel.route(endpoint, respond)
            await self.panel.locator("#qdrant-test").click()
            await expect(self.panel.locator("#qdrant-status")).to_contain_text(message)
            self.assertNotIn("secret", await self.panel.locator("#qdrant-status").inner_text())
            self.assertEqual(await self.stores(), before)
        await self.panel.unroute(endpoint)
        await self.panel.route(endpoint, lambda route: route.abort())
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("Could not connect")
        await self.panel.evaluate("""() => {
            AbortSignal.timeout = () => AbortSignal.abort(new DOMException('Timed out', 'TimeoutError'));
        }""")
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("timed out")
        self.assertEqual(await self.stores(), before)
        await self.panel.locator("#qdrant-reset").click()
        await expect(self.panel.locator("#qdrant-key")).to_have_value("qdrant-test-secret")

    async def test_invalid_endpoints_never_receive_credentials(self):
        requests = []

        async def reject_request(route):
            requests.append(route.request.url)
            await route.abort()

        await self.panel.route("**/*", reject_request)
        await self.fill_qdrant()
        for url in [
            "http://test.cloud.qdrant.io:6333", "https://example.com", "https://test.cloud.qdrant.io.evil.test",
            "https://user:password@test.cloud.qdrant.io", "https://test.cloud.qdrant.io/collections",
            "https://test.cloud.qdrant.io?key=secret", "https://test.cloud.qdrant.io:6334",
        ]:
            await self.panel.locator("#qdrant-url").fill(url)
            await self.panel.locator("#qdrant-test").click()
            await expect(self.panel.locator("#qdrant-status")).to_contain_text("Use your Qdrant Cloud")
        self.assertEqual(requests, [])
        self.assertNotIn("qdrant", (await self.stores())["session"])

    async def test_pending_and_invalid_json_response_do_not_save(self):
        finish = asyncio.Event()

        async def respond(route):
            await finish.wait()
            await route.fulfill(content_type="application/json", body="not-json-provider-secret")

        await self.panel.route("https://test.cloud.qdrant.io:6333/**", respond)
        await self.fill_qdrant()
        await self.panel.locator("#qdrant-test").click()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("Checking")
        await expect(self.panel.locator("#qdrant-test")).to_be_disabled()
        await expect(self.panel.locator("#qdrant-key")).to_be_disabled()
        await expect(self.panel.locator("#qdrant-url")).to_be_disabled()
        self.assertNotIn("qdrant", (await self.stores())["session"])
        finish.set()
        await expect(self.panel.locator("#qdrant-status")).to_contain_text("invalid response")
        self.assertNotIn("provider-secret", await self.panel.locator("#qdrant-status").inner_text())
        await expect(self.panel.locator("#qdrant-test")).to_be_enabled()
        self.assertNotIn("qdrant", (await self.stores())["session"])
