.PHONY: test lint ci ci_full typecheck_frontend check_frontend_api_slices check_frontend_api_no_monolithic_schema test_bff test_api test_api_full test_server test_scripts test_frontend generate generate_frontend_api inference_corpus inference_corpus_discover inference_corpus_probe

# Use workspace venv (Python 3.14) and ensure dev deps (pytest, ruff) are installed.
# `test` runs lint and unit tests (API fast suite; see `test_api_full` for solver/corpus integration).
# `ci` also runs the full frontend `tsc -b` (see `typecheck_frontend`).
test: lint test_bff test_api test_server test_scripts test_frontend

# Fast PR/iteration loop: lint, schema checks, typecheck, tests excluding @pytest.mark.slow API cases.
ci: lint check_frontend_api_slices check_frontend_api_no_monolithic_schema typecheck_frontend test_bff test_api test_server test_scripts test_frontend

# Full validation including slow OR-Tools / inference-corpus integration tests (`test_api_full`).
ci_full: lint check_frontend_api_slices check_frontend_api_no_monolithic_schema typecheck_frontend test_bff test_api_full test_server test_scripts test_frontend

# Regenerate checked-in artefacts from source (BFF OpenAPI -> frontend TypeScript types).
generate: generate_frontend_api

generate_frontend_api:
	uv sync --extra dev
	cd packages/frontend && npm run generate:api

# Fail if committed schema-<slice>.ts drift from BFF OpenAPI (dump + filter + openapi-typescript --check).
check_frontend_api_slices:
	uv sync --extra dev
	cd packages/frontend && npm run check:api:slices

# Fail if monolithic packages/frontend/src/api/schema.ts reappears (ADR 0003; issue #60).
check_frontend_api_no_monolithic_schema:
	uv sync --extra dev
	uv run python scripts/check_no_monolithic_schema.py

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
	PYTHONPATH=packages/api uv run python -m pytest packages/api/tests -m "not slow"

test_api_full:
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

inference_corpus:
	uv sync --extra dev
ifndef GAME_ID
	$(error GAME_ID is required, e.g. make inference_corpus GAME_ID=628580)
endif
	PYTHONPATH=packages/api uv run python scripts/run_inference_corpus.py --game-id $(GAME_ID) $(if $(STORAGE_ROOT),--storage-root $(STORAGE_ROOT),) $(if $(FROM_TURN),--from-turn $(FROM_TURN),) $(if $(TO_TURN),--to-turn $(TO_TURN),)

inference_corpus_discover:
	uv sync --extra dev
ifndef GAME_ID
	$(error GAME_ID is required, e.g. make inference_corpus_discover GAME_ID=628580)
endif
	uv run python scripts/run_inference_corpus.py discover --game-id $(GAME_ID) $(if $(STORAGE_ROOT),--storage-root $(STORAGE_ROOT),) $(if $(FROM_TURN),--from-turn $(FROM_TURN),) $(if $(TO_TURN),--to-turn $(TO_TURN),)

# Walk stored turn pairs for a finished game (default 628580) in host-turn order; stop once
# the solver accumulates STOP_AFTER_FAILURES inference failures (default 10) or
# PROBE_TIME_LIMIT_SECONDS elapses (default 300). Skips do not count toward the failure budget.
# Cases run in a process pool of PROBE_WORKERS (default 4).
inference_corpus_probe:
	uv sync --extra dev
	PYTHONPATH=packages/api uv run python scripts/run_inference_corpus.py \
		--game-id $(or $(GAME_ID),628580) \
		--stop-after-failures $(or $(STOP_AFTER_FAILURES),10) \
		--probe-time-limit-seconds $(or $(PROBE_TIME_LIMIT_SECONDS),300) \
		--workers $(or $(PROBE_WORKERS),4) \
		$(if $(STORAGE_ROOT),--storage-root $(STORAGE_ROOT),) \
		$(if $(FROM_TURN),--from-turn $(FROM_TURN),) \
		$(if $(TO_TURN),--to-turn $(TO_TURN),) \
		$(if $(MAX_COMPLEXITY),--max-complexity $(MAX_COMPLEXITY),)
