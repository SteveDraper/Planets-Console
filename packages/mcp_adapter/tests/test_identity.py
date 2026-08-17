"""Tests for MCP login identity extraction and credential probe (fail closed)."""

from __future__ import annotations

import pytest
from api.errors import ValidationError
from mcp_adapter.errors import LoginProbeFailedError, MissingLoginIdentityError
from mcp_adapter.identity import LOGIN_HEADER, require_login_identity


def test_missing_login_header_is_adapter_error():
    with pytest.raises(MissingLoginIdentityError) as exc:
        require_login_identity(None, probe=lambda name: True)
    assert LOGIN_HEADER in str(exc.value)


def test_blank_login_header_is_adapter_error():
    with pytest.raises(MissingLoginIdentityError):
        require_login_identity({LOGIN_HEADER: "  "}, probe=lambda name: True)


def test_header_lookup_is_case_insensitive():
    headers = {"x-planets-nu-login": "alice"}
    assert require_login_identity(headers, probe=lambda name: True) == "alice"


def test_probe_false_is_adapter_error():
    with pytest.raises(LoginProbeFailedError) as exc:
        require_login_identity({LOGIN_HEADER: "alice"}, probe=lambda name: False)
    assert "alice" in str(exc.value)


def test_probe_validation_error_fails_closed():
    def probe(_name: str) -> bool:
        raise ValidationError("username must be non-empty")

    with pytest.raises(LoginProbeFailedError):
        require_login_identity({LOGIN_HEADER: "bad name"}, probe=probe)


def test_probe_true_returns_login_name():
    seen: list[str] = []

    def probe(name: str) -> bool:
        seen.append(name)
        return True

    assert require_login_identity({LOGIN_HEADER: " alice "}, probe=probe) == "alice"
    assert seen == ["alice"]
