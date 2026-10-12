.PHONY: dev dev-isolated build test store-status

dev:
	uv run python -m src.dev

dev-isolated:
	uv run python -m src.dev --isolated

build:
	uv run python -m src.build --preview

store-status:
	uv run --env-file .env python -m src.webstore status

test:
	npm run check
	npm run build
	npm test
	uv run python -m unittest discover -s tests
