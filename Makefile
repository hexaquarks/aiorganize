.PHONY: run apply-chrome test package-extension store-status

run:
	uv run --env-file .env python -m demos.extension_chrome

apply-chrome:
	uv run --env-file .env python -m demos.apply_live_chrome

package-extension:
	uv run python -m src.package_extension --preview

store-status:
	uv run --env-file .env python -m src.webstore status

test:
	uv run python -m tests.integration.test_chrome --browser-only --headless
	uv run python -m unittest discover -s tests
