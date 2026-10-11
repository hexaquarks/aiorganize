.PHONY: dev build test store-status

dev:
	uv run python -m src.dev

build:
	uv run python -m src.build --preview

store-status:
	uv run --env-file .env python -m src.webstore status

test:
	uv run python -m unittest discover -s tests
