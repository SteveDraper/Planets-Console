.PHONY: test test_bff test_api test_frontend

test: test_bff test_api test_frontend

test_bff:
	cd packages/bff && uv run pytest

test_api:
	cd packages/api && uv run pytest

test_frontend:
	@echo "No frontend tests configured yet."
