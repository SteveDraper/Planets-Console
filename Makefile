.PHONY: test lint test_bff test_api test_server test_frontend

# Use workspace venv (Python 3.14) and ensure dev deps (pytest, ruff) are installed.
test: lint test_bff test_api test_server test_frontend

lint:
	uv sync --extra dev
	uv run ruff check packages/api packages/bff packages/server scripts
	uv run ruff format --check packages/api packages/bff packages/server scripts

test_bff:
	uv sync --extra dev
	PYTHONPATH=packages/bff:packages/api uv run python -m pytest packages/bff/tests

test_api:
	uv sync --extra dev
	PYTHONPATH=packages/api uv run python -m pytest packages/api/tests

test_server:
	uv sync --extra dev
	PYTHONPATH=packages/server:packages/api:packages/bff uv run python -m pytest packages/server/tests

test_frontend:
	@echo "No frontend tests configured yet."
