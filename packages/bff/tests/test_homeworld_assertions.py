"""BFF homeworld locator assertion / refresh contract tests (#37 Phase 2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bff.app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_bff_assertion_proxies_to_core() -> None:
    mock_core = MagicMock()
    mock_core.apply_homeworld_assertion.return_value = {
        "analyticId": "homeworld-locator",
        "available": True,
        "rows": [{"planetId": 3, "assertedCue": True}],
        "markers": [{"planetId": 3, "assertedCue": True}],
    }
    with patch("bff.routers.homeworld_locator.get_core_client", return_value=mock_core):
        response = client.post(
            "/analytics/homeworld-locator/assertions?gameId=628580&turn=111&perspective=1",
            json={"axis": "location", "action": "upsert", "planetId": 3},
        )
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["assertedCue"] is True
    mock_core.apply_homeworld_assertion.assert_called_once_with(
        628580,
        1,
        111,
        axis="location",
        action="upsert",
        planet_id=3,
        sector_index=None,
        owner_slot=None,
        username="",
    )


def test_bff_refresh_proxies_to_core() -> None:
    mock_core = MagicMock()
    mock_core.refresh_homeworld_locator.return_value = {
        "analyticId": "homeworld-locator",
        "available": True,
        "rows": [],
        "markers": [],
    }
    with patch("bff.routers.homeworld_locator.get_core_client", return_value=mock_core):
        response = client.post(
            "/analytics/homeworld-locator/refresh?gameId=628580&turn=111&perspective=1",
        )
    assert response.status_code == 200, response.text
    mock_core.refresh_homeworld_locator.assert_called_once_with(628580, 1, 111, username="")


def test_bff_assertion_forwards_username_to_core() -> None:
    mock_core = MagicMock()
    mock_core.apply_homeworld_assertion.return_value = {
        "analyticId": "homeworld-locator",
        "available": True,
        "rows": [],
        "markers": [],
    }
    with patch("bff.routers.homeworld_locator.get_core_client", return_value=mock_core):
        response = client.post(
            "/analytics/homeworld-locator/assertions"
            "?gameId=628580&turn=111&perspective=1&username=captain",
            json={"axis": "location", "action": "upsert", "planetId": 3},
        )
    assert response.status_code == 200, response.text
    assert mock_core.apply_homeworld_assertion.call_args.kwargs["username"] == "captain"


def test_bff_refresh_forwards_username_to_core() -> None:
    mock_core = MagicMock()
    mock_core.refresh_homeworld_locator.return_value = {
        "analyticId": "homeworld-locator",
        "available": True,
        "rows": [],
        "markers": [],
    }
    with patch("bff.routers.homeworld_locator.get_core_client", return_value=mock_core):
        response = client.post(
            "/analytics/homeworld-locator/refresh"
            "?gameId=628580&turn=111&perspective=1&username=captain",
        )
    assert response.status_code == 200, response.text
    mock_core.refresh_homeworld_locator.assert_called_once_with(628580, 1, 111, username="captain")


def test_fleet_age_refetch_passes_after_epoch():
    mock_core = MagicMock()
    mock_core.fleet_age_refetch_notice.return_value = {"epoch": 4, "fromTurn": 2}
    with patch("bff.routers.homeworld_locator.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/homeworld-locator/fleet-age-refetch?gameId=628580&perspective=1&afterEpoch=3"
        )
    assert response.status_code == 200
    assert response.json() == {"epoch": 4, "fromTurn": 2}
    mock_core.fleet_age_refetch_notice.assert_called_once_with(628580, 1, after_epoch=3)
