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
            await route.fulfill(
                json={
                    "data": [
                        {"id": "gpt-6.1-sol", "created": 1},
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
                    ]
                }
            )

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#api-key").fill("model-list-test-key")
        await self.panel.locator("#api-model").click()

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("2 models available with this key.")
        await expect(self.panel.get_by_role("listbox")).to_be_visible()
        self.assertEqual(
            await self.panel.get_by_role("option").all_text_contents(),
            [
                "GPT-6.1 Sol",
                "GPT-5 Mini",
            ],
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].headers["authorization"], "Bearer model-list-test-key")
        self.assertIsNone(requests[0].post_data)

        await self.panel.get_by_role("option", name="GPT-5 Mini", exact=True).click()

        await expect(self.panel.locator("#organize")).to_be_disabled()
        settings = await self.read_settings()
        self.assertFalse(settings["apiKey"])

        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option", name="GPT-5 Mini", exact=True)).to_be_focused()
        self.assertEqual(len(requests), 1)

        await self.panel.set_viewport_size({"width": 462, "height": 800})
        await self.panel.screenshot(path="dist/available-models-preview.png", full_page=True)

        await self.panel.keyboard.press("Escape")
        validation_requests = []

        async def validate(route):
            request = route.request.post_data_json
            validation_requests.append(request)
            tabs = json.loads(request["input"])["tabs"]
            await route.fulfill(
                json={
                    "status": "completed",
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "groups": [
                                                {"name": "Test", "tab_ids": [tab["id"] for tab in tabs]},
                                            ]
                                        }
                                    ),
                                }
                            ]
                        }
                    ],
                }
            )

        await self.panel.route("https://api.openai.com/v1/responses", validate)
        await self.panel.locator("#test-connection").click()

        await expect(self.panel.locator("#ready")).to_be_visible()
        self.assertEqual(validation_requests[0]["model"], "gpt-5-mini")
        self.assertEqual(len(json.loads(validation_requests[0]["input"])["tabs"]), 2)
        settings = await self.read_settings()
        self.assertEqual(settings["model"], "gpt-5-mini")
        await expect(self.panel.locator("#organize")).to_be_enabled()

    async def test_account_refresh_keeps_the_shortlist_at_most_fifteen(self):
        await self.panel.locator("#api-model").click()

        ids = await self.panel.get_by_role("option").evaluate_all(
            "elements => elements.map(element => element.dataset.value)"
        )

        await self.panel.keyboard.press("Escape")
        await self.panel.unroute("https://api.openai.com/v1/models")
        data = [{"id": model, "created": index} for index, model in enumerate(ids)]
        data += [{"id": model + "-2026-04-23", "created": 100} for model in ids]
        data += [{"id": model, "created": 200} for model in ["gpt-4o", "o1", "o3", "gpt-5"]]
        await self.panel.route("https://api.openai.com/v1/models", lambda route: route.fulfill(json={"data": data}))
        await self.panel.locator("#api-key").fill("shortlist-test-key")

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("15 models available with this key.")

        await self.panel.locator("#api-model").click()
        options = self.panel.get_by_role("option")
        await expect(options).to_have_count(15)
        account_ids = await options.evaluate_all("elements => elements.map(element => element.dataset.value)")
        self.assertEqual(set(account_ids), set(ids))
        self.assertEqual(account_ids[0], "gpt-6.1-sol")

    async def test_discovery_failure_does_not_replace_working_settings(self):
        await self.connect()

        before = await self.read_settings()

        await self.panel.unroute("https://api.openai.com/v1/models")
        count = 0

        async def respond(route):
            nonlocal count
            count += 1
            await route.fulfill(status=403, json={"error": {"message": "SECRET PROVIDER DETAIL"}})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#settings-toggle").click()

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text(
            "OpenAI denied model-list access (403)"
        )
        self.assertNotIn("SECRET PROVIDER DETAIL", await self.panel.locator("body").inner_text())

        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option", name="GPT-6.1 Sol", exact=True)).to_be_visible()
        await expect(self.panel.locator("#model-discovery-status")).to_contain_text(
            "OpenAI denied model-list access (403)"
        )
        self.assertGreaterEqual(count, 2)
        current = await self.read_settings()
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
                await route.fulfill(json={"data": [{"id": "gpt-5.5", "created": 10}]})
            else:
                await route.fulfill(json={"data": [{"id": "gpt-6.1-sol", "created": 11}]})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.locator("#api-key").fill("old-test-key")
        await self.panel.locator("#api-model").click()
        await asyncio.wait_for(started.wait(), timeout=5)
        await self.panel.locator("#api-key").fill("new-test-key")
        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option", name="GPT-6.1 Sol", exact=True)).to_be_visible()
        release.set()
        await expect(self.panel.locator('#model-options [data-value="gpt-5.5"]')).to_have_count(0)
        stores = await self.panel.evaluate("""async () => ({
            local: await chrome.storage.local.get(), session: await chrome.storage.session.get(),
        })""")
        self.assertNotIn("test-key", json.dumps(stores))

    async def test_key_entry_loads_models_without_blur_and_refresh_bypasses_cache(self):
        await self.panel.unroute("https://api.openai.com/v1/models")
        requests = []

        async def respond(route):
            requests.append(route.request)
            await route.fulfill(
                json={
                    "data": [
                        {"id": "gpt-6.1-sol", "created": 1},
                        {"id": "gpt-5.5" if len(requests) == 1 else "gpt-6.1-sol", "created": 2},
                    ]
                }
            )

        await self.panel.route("https://api.openai.com/v1/models", respond)

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("Supported models")
        await expect(self.panel.locator("#refresh-models")).to_be_disabled()

        await self.panel.locator("#api-key").fill("automatic-discovery-test-key")

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("2 models available with this key.")
        await expect(self.panel.locator("#api-key")).to_be_focused()

        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option", name="GPT-5.5", exact=True)).to_be_visible()
        self.assertEqual(len(requests), 1)

        await self.panel.locator("#refresh-models").click()

        await expect(self.panel.locator('#model-options [data-value="gpt-6.1-sol"]')).to_have_count(1)
        self.assertEqual(len(requests), 2)

        await self.panel.locator("#api-key").fill("")

        await expect(self.panel.locator("#refresh-models")).to_be_disabled()
        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("Supported models")

    async def test_saved_unverified_key_loads_models_on_startup(self):
        await self.panel.evaluate("""() => chrome.storage.session.set({apiKey: 'startup-test-key'})""")
        await self.panel.unroute("https://api.openai.com/v1/models")
        requests = []

        async def respond(route):
            requests.append(route.request)
            await route.fulfill(json={"data": [{"id": "gpt-5.5", "created": 2}]})

        await self.panel.route("https://api.openai.com/v1/models", respond)
        await self.panel.reload()

        await expect(self.panel.locator("#model-discovery-status")).to_contain_text("1 model available with this key.")
        self.assertEqual(requests[0].headers["authorization"], "Bearer startup-test-key")

        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option", name="GPT-5.5", exact=True)).to_be_visible()
        await expect(self.panel.locator("#organize")).to_be_disabled()

    async def test_curated_catalog_is_available_before_key_entry(self):
        requests = []
        await self.panel.unroute("https://api.openai.com/v1/models")

        async def respond(route):
            requests.append(route.request)
            await route.abort()

        await self.panel.route("https://api.openai.com/v1/models", respond)

        await expect(self.panel.locator("#api-key")).to_be_empty()
        await expect(self.panel.locator("#api-model")).to_contain_text("GPT-6.1 Sol")
        settings = await self.read_settings()
        self.assertEqual(settings["model"], "gpt-6.1-sol")

        await self.panel.locator("#api-model").click()
        options = self.panel.get_by_role("option")
        await expect(options).to_have_count(15)
        ids = await options.evaluate_all("elements => elements.map(element => element.dataset.value)")
        expected_aliases = {
            "gpt-4.1-mini",
            "gpt-6.1-sol",
            "gpt-6-astra",
            "gpt-6-luna",
            "gpt-6-sol",
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.5",
            "gpt-5.5-pro",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.2",
            "gpt-5-mini",
        }
        self.assertEqual(expected_aliases, set(ids))
        self.assertEqual(ids[0], "gpt-6.1-sol")
        self.assertEqual(len(ids), len(set(ids)))
        for unsupported in [
            "gpt-3.5-turbo",
            "gpt-4",
            "gpt-4.5-preview",
            "codex-mini-latest",
            "gpt-5.2-pro",
            "gpt-5.4-pro",
            "gpt-image-1",
            "gpt-audio",
            "gpt-oss-120b",
        ]:
            self.assertNotIn(unsupported, ids)
        self.assertEqual(requests, [])

        await self.panel.get_by_role("option", name="GPT-6.1 Sol", exact=True).click()

        self.assertEqual(await self.panel.locator("#api-model").evaluate("element => element.value"), "gpt-6.1-sol")
        await expect(self.panel.locator("#test-connection")).to_be_disabled()
        await expect(self.panel.locator("#organize")).to_be_disabled()

        await self.panel.reload()
        await self.panel.locator("#api-model").click()

        await expect(self.panel.get_by_role("option")).to_have_count(15)
        self.assertEqual(requests, [])

        await self.panel.set_viewport_size({"width": 462, "height": 800})
        await self.panel.screenshot(path="dist/models-before-key-preview.png", full_page=True)
