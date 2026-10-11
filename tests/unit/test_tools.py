import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.tools import chrome_read_tab_tool, chrome_tab_tool


class ScopedTabToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_uses_extension_state_without_reading_browser_pages(self):
        worker = SimpleNamespace(evaluate=AsyncMock(return_value={
            "tabs": [
                {"id": "one", "title": "Python", "url": "https://example.test", "window_id": 7},
                {"id": "two", "title": "Other", "url": "https://other.test", "window_id": 8},
            ]
        }))

        tabs = await chrome_tab_tool(object(), worker=worker, window_id=7).ainvoke({})

        self.assertEqual(tabs, [{"id": "one", "title": "Python", "url": "https://example.test"}])

    async def test_unreadable_page_returns_a_fallback_instead_of_failing(self):
        locator = SimpleNamespace(inner_text=AsyncMock(side_effect=PlaywrightTimeoutError("Timed out")))
        page = SimpleNamespace(url="https://example.test", locator=lambda selector: locator)
        with patch("src.tools._tab_pages", new=AsyncMock(return_value=[("one", page)])):
            result = await chrome_read_tab_tool(object()).ainvoke({"tab_id": "one"})

        self.assertEqual(result["content"], "")
        self.assertIn("unavailable", result["note"])


if __name__ == "__main__":
    unittest.main()
