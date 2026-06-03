.PHONY: test lint ci typecheck_frontend check_frontend_api_slices test_bff test_api test_server test_scripts test_frontend generate generate_frontend_api

# Use workspace venv (Python 3.14) and ensure dev deps (pytest, ruff) are installed.
# `test` runs lint and unit tests. `ci` also runs the full frontend `tsc -b` (see `typecheck_frontend`).
test: lint test_bff test_api test_server test_scripts test_frontend

# Everything CI should run: Python lint, committed schema slice freshness, frontend typecheck, then all test suites.
ci: lint check_frontend_api_slices typecheck_frontend test_bff test_api test_server test_scripts test_frontend

# Regenerate checked-in artefacts from source (BFF OpenAPI -> frontend TypeScript types).
generate: generate_frontend_api

generate_frontend_api:
	uv sync --extra dev
	cd packages/frontend && npm run generate:api

# Fail if committed schema-<slice>.ts drift from BFF OpenAPI (dump + filter + openapi-typescript --check).
check_frontend_api_slices:
	uv sync --extra dev
	cd packages/frontend && npm run check:api:slices

# Full TypeScript project build for packages/frontend (tsconfig app + node / Vite).
typecheck_frontend:
	cd packages/frontend && npx tsc -b

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

test_scripts:
	uv sync --extra dev
	PYTHONPATH=scripts:packages/bff:packages/api uv run python -m pytest scripts/tests

test_frontend:
	cd packages/frontend && npm run test
