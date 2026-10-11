import json

from playwright.async_api import expect

from tests.integration.test_panel import PanelTestCase


class ConnectionSetupTest(PanelTestCase):
    async def test_synthetic_validation_storage_reveal_and_reload(self):
        requests = []

        async def respond(route):
            request = route.request.post_data_json
            requests.append(request)
            tabs = json.loads(request["input"])["tabs"]
            await route.fulfill(json={"status": "completed", "output": [{"content": [{
                "type": "output_text", "text": json.dumps({"groups": [
                    {"name": "Test", "tab_ids": [tab["id"] for tab in tabs]},
                ]}),
            }]}]})

        await self.panel.route("https://api.openai.com/v1/responses", respond)
        await self.panel.locator("#api-key").fill("synthetic-secret")
        await self.panel.get_by_role("button", name="Show API key").click()
        await expect(self.panel.locator("#api-key")).to_have_attribute("type", "text")
        await self.panel.get_by_role("button", name="Hide API key").click()
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#ready")).to_be_visible()
        await expect(self.panel.locator("#organize")).to_be_enabled()
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request["model"], "gpt-6.1-sol")
        self.assertFalse(request["store"])
        self.assertEqual(request["text"]["format"]["name"], "tab_groups")
        tabs = json.loads(request["input"])["tabs"]
        self.assertEqual(len(tabs), 2)
        self.assertTrue(all(tab["url"].startswith("https://example.com/") for tab in tabs))
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertNotIn("synthetic-secret", json.dumps(stores["local"]))
        self.assertEqual(stores["session"]["connection"]["apiKey"], "synthetic-secret")
        await self.panel.reload()
        await expect(self.panel.locator("#ready")).to_be_visible()
        await expect(self.panel.locator("#api-settings")).to_be_hidden()
        await self.panel.locator("#forget-key").click()
        await expect(self.panel.locator("#api-settings")).to_be_visible()
        await expect(self.panel.locator("#organize")).to_be_disabled()
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertNotIn("synthetic-secret", json.dumps(stores))

    async def test_failed_replacements_preserve_working_connection(self):
        await self.connect(remember=True)
        before = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertEqual(stores["local"]["connection"]["apiKey"], "test-secret")
        self.assertNotIn("connection", stores["session"])
        await self.panel.locator("#edit-connection").click()
        await expect(self.panel.locator("#key-label")).to_have_text("Replace key")
        await self.panel.locator("#api-key").fill("replacement-secret")
        await expect(self.panel.locator("#organize")).to_be_disabled()
        for status, code, message, action in [
            (401, "invalid_api_key", "Key rejected", "Edit key"),
            (403, "permission_denied", "Key rejected", "Edit key"),
            (404, "model_not_found", "Choose another model", "Choose model"),
            (429, "insufficient_quota", "Billing needs attention", "Open billing"),
            (429, "rate_limit_exceeded", "Try again shortly", "Retry"),
            (503, "server_error", "Could not connect", "Retry"),
        ]:
            async def respond(route, *, status=status, code=code):
                await route.fulfill(status=status, json={"error": {"code": code, "message": "DO NOT SHOW SECRET"}})

            await self.panel.unroute("https://api.openai.com/v1/responses")
            await self.panel.route("https://api.openai.com/v1/responses", respond)
            await self.panel.locator("#test-connection").click()
            await expect(self.panel.locator("#settings-status")).to_contain_text(message)
            await expect(self.panel.locator("#settings-status")).to_contain_text(action)
            self.assertNotIn("DO NOT SHOW SECRET", await self.panel.locator("#settings-status").inner_text())
            current = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
            self.assertEqual(before, current)
        await self.panel.locator("#cancel-settings").click()
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_invalid_schema_and_testing_state(self):
        async def respond(route):
            await self.panel.wait_for_function("() => window.finishValidation === true")
            await route.fulfill(json={"status": "completed", "output": [{"content": [{
                "type": "output_text", "text": '{"groups":[{"name":"Test","tab_ids":["invented"]}]}',
            }]}]})

        await self.panel.route("https://api.openai.com/v1/responses", respond)
        await self.panel.locator("#api-key").fill("test-secret")
        await self.panel.locator("#advanced").click()
        await self.panel.locator("#custom-model").fill("custom-model")
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#test-connection")).to_be_disabled()
        await expect(self.panel.locator("#api-key")).to_be_disabled()
        await expect(self.panel.locator("#settings-status")).to_contain_text("Your tabs are not sent")
        await self.panel.evaluate("window.finishValidation = true")
        await expect(self.panel.locator("#settings-status")).to_contain_text("Could not verify")
        await expect(self.panel.locator("#organize")).to_be_disabled()
        settings = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertFalse(settings["apiKey"])

    async def test_network_and_timeout_feedback(self):
        await self.panel.route("https://api.openai.com/v1/responses", lambda route: route.abort())
        await self.panel.locator("#api-key").fill("test-secret")
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#settings-status")).to_contain_text("Could not connect")
        await expect(self.panel.locator("#settings-status")).to_contain_text("Retry")
        await self.panel.evaluate("""() => {
            AbortSignal.timeout = () => AbortSignal.abort(new DOMException('Timed out', 'TimeoutError'));
        }""")
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#settings-status")).to_contain_text("Could not connect")
        await expect(self.panel.locator("#organize")).to_be_disabled()

    async def test_model_change_requires_validation_and_custom_model_is_used(self):
        await self.connect()
        before = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        await self.panel.locator("#edit-connection").click()
        await self.panel.locator("#api-model").click()
        await self.panel.get_by_role("option", name="GPT-5.5", exact=True).click()
        await expect(self.panel.locator("#organize")).to_be_disabled()
        current = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertEqual(before, current)
        await self.panel.locator("#advanced summary").click()
        await self.panel.locator("#custom-model").fill("gpt-4.1-mini-2025-04-14")
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#ready")).to_be_visible()
        settings = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertEqual(settings["model"], "gpt-4.1-mini-2025-04-14")
        await expect(self.panel.locator("#connection-detail")).to_contain_text(settings["model"])

    async def test_model_menu_stays_aligned_and_supports_keyboard_navigation(self):
        await self.panel.set_viewport_size({"width": 462, "height": 800})
        trigger = self.panel.locator("#api-model")
        menu = self.panel.get_by_role("listbox")
        await trigger.focus()
        await trigger.press("ArrowDown")
        await expect(menu).to_be_visible()
        await expect(self.panel.get_by_role("option", name="GPT-6.1 Sol", exact=True)).to_be_focused()
        trigger_box = await trigger.bounding_box()
        menu_box = await menu.bounding_box()
        self.assertEqual(trigger_box["x"], menu_box["x"])
        self.assertEqual(trigger_box["width"], menu_box["width"])
        await self.panel.screenshot(path="dist/model-dropdown-preview.png", full_page=True)
        await self.panel.keyboard.press("ArrowUp")
        await expect(self.panel.get_by_role("option", name="GPT-5 Mini", exact=True)).to_be_focused()
        await self.panel.keyboard.press("Enter")
        await expect(menu).to_be_hidden()
        await expect(trigger).to_be_focused()
        await expect(trigger).to_contain_text("GPT-5 Mini")
        self.assertEqual(await trigger.evaluate("element => element.value"), "gpt-5-mini")
        await trigger.click()
        await self.panel.keyboard.press("Escape")
        await expect(menu).to_be_hidden()
        await expect(trigger).to_have_attribute("aria-expanded", "false")
        await trigger.click()
        await self.panel.locator("#api-key").click()
        await expect(menu).to_be_hidden()
        await self.panel.set_viewport_size({"width": 320, "height": 800})
        await trigger.click()
        self.assertTrue(await self.panel.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth"
        ))
