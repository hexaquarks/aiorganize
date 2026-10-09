.PHONY: run test test-chrome test-chrome-browser test-grouping apply-chrome test-apply

run:
	uv run --env-file .env python -m demos.fake_tabs

test:
	uv run python -m unittest discover -s tests/unit

test-chrome:
	uv run --env-file .env python -m tests.integration.test_chrome

test-chrome-browser:
	uv run python -m tests.integration.test_chrome --browser-only --headless

test-grouping:
	uv run --env-file .env python -m tests.integration.test_chrome --group --scenario both

apply-chrome:
	uv run --env-file .env python -m demos.apply_chrome

test-apply:
	uv run python -m unittest tests.integration.test_apply_chrome
