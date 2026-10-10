.PHONY: run test

run:
	uv run --env-file .env python -m demos.apply_live_chrome

test:
	uv run python -m tests.integration.test_chrome --browser-only --headless
	uv run python -m unittest discover -s tests
