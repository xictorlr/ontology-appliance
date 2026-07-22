.PHONY: setup dev test verify emulators gateway

setup:
	corepack enable
	pnpm install --frozen-lockfile
	cd services/semantic-gateway && uv sync --dev --extra firebase

dev:
	pnpm dev

gateway:
	pnpm dev:gateway

emulators:
	pnpm emulators

test:
	pnpm test
	cd services/semantic-gateway && uv run pytest

verify:
	pnpm verify
	cd services/semantic-gateway && uv run ruff check .
	cd services/semantic-gateway && uv run pytest
