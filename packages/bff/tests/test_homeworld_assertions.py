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
    mock_core.refresh_homeworld_locator.assert_called_once_with(628580, 1, 111)
