.PHONY: run test test-chrome test-chrome-browser test-grouping

run:
	uv run --env-file .env python main.py

test:
	uv run python -m unittest test_agent

test-chrome:
	uv run --env-file .env python test_chrome.py

test-chrome-browser:
	uv run python test_chrome.py --browser-only --headless

test-grouping:
	uv run --env-file .env python test_chrome.py --group --scenario both
