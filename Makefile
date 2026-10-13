.PHONY: dev dev-isolated build test test-qdrant store-status backend

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
	npm run build -- --mode test
	npm test
	uv run python -m unittest discover -s tests

test-qdrant:
	npm run build -- --mode test
	QDRANT_LIVE_TEST=1 uv run --env-file .env python -m unittest tests.integration.test_live_qdrant

backend:
	uv run --env-file .env uvicorn src.backend:from_environment --factory --host 127.0.0.1 --port 8765
