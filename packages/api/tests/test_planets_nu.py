"""Tests for Planets.nu HTTP client."""

from unittest.mock import MagicMock, patch

import httpx
from api.planets_nu import PlanetsNuClient, _safe_httpx_error_summary


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


def test_load_turn_posts_form_body() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True, "rst": {"game": {"id": 1}}}
    mock_response.raise_for_status = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response

    with patch("api.planets_nu.httpx.Client", return_value=mock_client):
        client = PlanetsNuClient("https://api.planets.nu")
        client.load_turn(game_id=673864, turn=49, player_id=0, api_key="key123")

    mock_client.post.assert_called_once_with(
        "https://api.planets.nu/game/loadturn",
        data={"gameid": 673864, "turn": 49, "playerid": 0, "apikey": "key123"},
    )
    mock_client.get.assert_not_called()
