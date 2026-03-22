"""Tests for Planets.nu HTTP client."""

import httpx
from api.planets_nu import _safe_httpx_error_summary


def test_safe_httpx_error_summary_http_status_excludes_query_string() -> None:
    request = httpx.Request(
        "GET",
        "https://api.planets.nu/login?username=u&password=secret123",
    )
    response = httpx.Response(401, request=request)
    exc = httpx.HTTPStatusError("upstream", request=request, response=response)
    summary = _safe_httpx_error_summary(exc)
    assert "secret123" not in summary
    assert "password" not in summary
    assert "GET" in summary
    assert "/login" in summary
    assert "401" in summary


def test_safe_httpx_error_summary_request_error_excludes_query_string() -> None:
    request = httpx.Request(
        "GET",
        "https://api.planets.nu/game/loadturn?apikey=sekret&gameid=1",
    )
    exc = httpx.ConnectError("failed", request=request)
    summary = _safe_httpx_error_summary(exc)
    assert "sekret" not in summary
    assert "apikey" not in summary
    assert "/game/loadturn" in summary
    assert "ConnectError" in summary


def test_safe_httpx_error_summary_unknown_subclass() -> None:
    class OddError(httpx.HTTPError):
        pass

    exc = OddError("x")
    assert _safe_httpx_error_summary(exc) == "OddError"
