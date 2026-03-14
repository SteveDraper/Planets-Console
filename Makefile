.PHONY: test test_bff test_api test_frontend

test: test_bff test_api test_frontend

test_bff:
	uv run --package bff pytest

test_api:
	@echo "No api tests configured yet."

test_frontend:
	@echo "No frontend tests configured yet."
