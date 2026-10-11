import asyncio
import json

from playwright.async_api import expect

from tests.integration.test_panel import PanelTestCase


class ModelDiscoveryTest(PanelTestCase):
    async def test_account_models_are_filtered_sorted_and_must_be_tested(self):
        requests = []
        await self.panel.unroute("https://api.openai.com/v1/models")

        async def respond(route):
            requests.append(route.request)
            await route.fulfill(json={"data": [
                {"id": "gpt-4.1-mini", "created": 1},
                {"id": "gpt-5-mini", "created": 10},
                {"id": "gpt-5-mini", "created": 10},
                {"id": "gpt-5", "created": 9},
                {"id": "gpt-5-2025-08-07", "created": 8},
                {"id": "o3", "created": 7},
                {"id": "ft:gpt-4.1-mini:example:custom", "created": 6},
                {"id": "gpt-4.1", "created": 5, "shutdown_date": "2000-01-01"},
                {"id": "gpt-4o-2024-05-13", "created": 5},
                {"id": "gpt-4", "created": 5},
                {"id": "o1-preview", "created": 5},
                {"id": "gpt-5-search-api", "created": 5},
                {"id": "gpt-audio", "created": 5},
                {"id": "gpt-realtime", "created": 5},
                {"id": "gpt-image-1", "created": 5},
                {"id": "text-embedding-3-small", "created": 5},
                {"id": "whisper-1", "created": 5},
                {"id": "omni-moderation-latest", "created": 5},
                {"id": "o3-deep-research", "created": 5},
                {"id": "<script>unsafe</script>", "created": 5},
                {"id": None},
            ]})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#api-key").fill("model-list-test-key")
        await self.panel.locator("#api-model").click()
        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("then newest")
        await expect(self.panel.get_by_role("listbox")).to_be_visible()
        self.assertEqual(await self.panel.get_by_role("option").all_text_contents(), [
            "GPT-4.1 mini", "gpt-5-mini", "gpt-5", "gpt-5-2025-08-07", "o3",
            "ft:gpt-4.1-mini:example:custom",
        ])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].headers["authorization"], "Bearer model-list-test-key")
        self.assertIsNone(requests[0].post_data)
        await self.panel.get_by_role("option", name="gpt-5-mini", exact=True).click()
        await expect(self.panel.locator("#organize")).to_be_disabled()
        settings = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertFalse(settings["apiKey"])
        await self.panel.locator("#api-model").click()
        await expect(self.panel.get_by_role("option", name="gpt-5-mini", exact=True)).to_be_focused()
        self.assertEqual(len(requests), 1)
        await self.panel.set_viewport_size({"width": 462, "height": 800})
        await self.panel.screenshot(path="dist/available-models-preview.png", full_page=True)

        await self.panel.keyboard.press("Escape")
        validation_requests = []

        async def validate(route):
            request = route.request.post_data_json
            validation_requests.append(request)
            tabs = json.loads(request["input"])["tabs"]
            await route.fulfill(json={"status": "completed", "output": [{"content": [{
                "type": "output_text", "text": json.dumps({"groups": [
                    {"name": "Test", "tab_ids": [tab["id"] for tab in tabs]},
                ]}),
            }]}]})

        await self.panel.route("https://api.openai.com/v1/responses", validate)
        await self.panel.locator("#test-connection").click()
        await expect(self.panel.locator("#ready")).to_be_visible()
        self.assertEqual(validation_requests[0]["model"], "gpt-5-mini")
        self.assertEqual(len(json.loads(validation_requests[0]["input"])["tabs"]), 2)
        settings = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertEqual(settings["model"], "gpt-5-mini")
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_discovery_failure_does_not_replace_working_settings(self):
        await self.connect()
        before = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        await self.panel.unroute("https://api.openai.com/v1/models")
        count = 0

        async def respond(route):
            nonlocal count
            count += 1
            await route.fulfill(status=403, json={"error": {"message": "SECRET PROVIDER DETAIL"}})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#edit-connection").click()
        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("Could not load")
        self.assertNotIn("SECRET PROVIDER DETAIL", await self.panel.locator("body").inner_text())
        await self.panel.locator("#api-model").click()
        await expect(self.panel.get_by_role("option", name="GPT-4.1 mini", exact=True)).to_be_visible()
        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("Could not load")
        self.assertGreaterEqual(count, 2)
        current = await self.panel.evaluate("async () => (await import('./settings.js')).getSettings()")
        self.assertEqual(before, current)
        await self.panel.locator("#cancel-settings").click()
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_replacement_key_cancels_stale_model_discovery(self):
        started = asyncio.Event()
        release = asyncio.Event()
        await self.panel.unroute("https://api.openai.com/v1/models")

        async def respond(route):
            if route.request.headers["authorization"] == "Bearer old-test-key":
                started.set()
                await release.wait()
                await route.fulfill(json={"data": [{"id": "gpt-5-old-account", "created": 10}]})
            else:
                await route.fulfill(json={"data": [{"id": "gpt-5-new-account", "created": 11}]})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#api-key").fill("old-test-key")
        await self.panel.locator("#api-model").click()
        await asyncio.wait_for(started.wait(), timeout=5)
        await self.panel.locator("#api-key").fill("new-test-key")
        await self.panel.locator("#api-model").click()
        await expect(self.panel.get_by_role("option", name="gpt-5-new-account", exact=True)).to_be_visible()
        release.set()
        self.assertNotIn("gpt-5-old-account", await self.panel.locator("#model-options").inner_text())
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertNotIn("test-key", json.dumps(stores))
