"""Tests for PlanetsNuClient.games_list."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from api.errors import UpstreamPlanetsError
from api.planets_nu import PlanetsNuClient


def test_games_list_parses_array_response():
    client = PlanetsNuClient("https://api.planets.nu")
    response = MagicMock()
    response.json.return_value = [{"id": 1, "name": "Sector"}]
    response.raise_for_status = MagicMock()

    with patch("api.planets_nu.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = response
        games = client.games_list(status=3, scope=0)

    assert games == [{"id": 1, "name": "Sector"}]


def test_games_list_parses_wrapped_response():
    client = PlanetsNuClient("https://api.planets.nu")
    response = MagicMock()
    response.json.return_value = {"success": True, "games": [{"id": 2}]}
    response.raise_for_status = MagicMock()

    with patch("api.planets_nu.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = response
        games = client.games_list()

    assert games == [{"id": 2}]


def test_games_list_raises_upstream_on_http_error():
    client = PlanetsNuClient("https://api.planets.nu")
    with patch("api.planets_nu.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = httpx.HTTPError("fail")
        with pytest.raises(UpstreamPlanetsError):
            client.games_list()
