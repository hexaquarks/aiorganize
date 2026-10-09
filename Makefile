.PHONY: run test-chrome test-chrome-browser

run:
	uv run --env-file .env python main.py

test-chrome:
	uv run --env-file .env python test_chrome.py

test-chrome-browser:
	uv run python test_chrome.py --browser-only --headless
