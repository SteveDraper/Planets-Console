"""League team directory: profile join, one fetch per id, durable cache, per-id failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.config import ApiConfig, set_config
from api.errors import NotFoundError, UpstreamPlanetsError
from api.services.game_service import GameService
from api.services.league_team_directory import (
    LeagueTeamDirectoryService,
    league_team_name_from_profile,
    league_team_store_key,
)
from api.storage import clear_backend_cache, get_storage
from api.transport.league_teams import LeagueTeamName
from fastapi.testclient import TestClient

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
SHADOWHAWKS = "Die Schattenfalken (The Shadowhawks)"
OTHER_GROUP = "Dockworkers"

PROFILE_76 = {
    "playergroups": [
        {
            "groupid": 12,
            "status": 1,
            "_group": {"id": 12, "isleague": False, "name": OTHER_GROUP},
        },
        {
            "groupid": 76,
            "status": 1,
            "_group": {"id": 76, "isleague": True, "name": SHADOWHAWKS},
        },
    ]
}


class _Profiles:
    def __init__(self, by_username: dict[str, dict | Exception]) -> None:
        self.calls: list[str] = []
        self._by_username = by_username

    def load_profile(self, username: str) -> dict:
        self.calls.append(username)
        payload = self._by_username[username]
        if isinstance(payload, Exception):
            raise payload
        return payload


@pytest.fixture
def storage():
    clear_backend_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    backend = get_storage()
    yield backend
    clear_backend_cache()


def _store_roster(storage, assignments: list[tuple[str, int]], *, game_id: int = 628580) -> None:
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        payload = json.load(handle)
    players = payload["players"]
    for index, player in enumerate(players):
        if index < len(assignments):
            username, team_id = assignments[index]
            player["username"] = username
            player["leagueteamid"] = team_id
        else:
            player["leagueteamid"] = 0
    storage.put(f"games/{game_id}/info", payload)


def _directory(storage) -> LeagueTeamDirectoryService:
    return LeagueTeamDirectoryService(storage, GameService(storage))


def test_profile_groupid_match_returns_group_name_and_ignores_other_group() -> None:
    assert league_team_name_from_profile(PROFILE_76, 76) == SHADOWHAWKS
    assert OTHER_GROUP not in (league_team_name_from_profile(PROFILE_76, 76) or "")
    assert league_team_name_from_profile(PROFILE_76, 999) is None


def test_leagueteamid_zero_is_absent(storage) -> None:
    _store_roster(storage, [("alpha", 76), ("solo", 0)])
    planets = _Profiles({"alpha": PROFILE_76})
    result = _directory(storage).teams_for_game(628580, planets)
    assert result.teams == [LeagueTeamName(id=76, name=SHADOWHAWKS)]
    assert 0 not in {team.id for team in result.teams}


def test_two_players_on_the_same_id_cause_one_profile_fetch(storage) -> None:
    _store_roster(storage, [("alpha", 76), ("beta", 76)])
    planets = _Profiles({"alpha": PROFILE_76, "beta": PROFILE_76})
    result = _directory(storage).teams_for_game(628580, planets)
    assert planets.calls == ["alpha"]
    assert result.teams == [LeagueTeamName(id=76, name=SHADOWHAWKS)]


def test_cached_id_is_returned_without_a_second_upstream_call(storage) -> None:
    _store_roster(storage, [("alpha", 76)])
    planets = _Profiles({"alpha": PROFILE_76})
    directory = _directory(storage)
    first = directory.teams_for_game(628580, planets)
    second = directory.teams_for_game(628580, planets)
    assert planets.calls == ["alpha"]
    assert first == second
    assert storage.get(league_team_store_key(76)) == {"id": 76, "name": SHADOWHAWKS}


def test_upstream_error_for_one_id_leaves_the_others_named(storage) -> None:
    _store_roster(storage, [("alpha", 76), ("broken", 88)])
    planets = _Profiles(
        {
            "alpha": PROFILE_76,
            "broken": UpstreamPlanetsError("Planets.nu load profile request failed."),
        }
    )
    result = _directory(storage).teams_for_game(628580, planets)
    assert result.teams == [
        LeagueTeamName(id=76, name=SHADOWHAWKS),
        LeagueTeamName(id=88, name=None),
    ]
    assert storage.get(league_team_store_key(76))["name"] == SHADOWHAWKS
    with pytest.raises(NotFoundError):
        storage.get(league_team_store_key(88))


def test_team_information_analytic_does_not_import_directory() -> None:
    import api.analytics.team_information as team_information

    text = Path(team_information.__file__).read_text(encoding="utf-8")
    assert "league_team_directory" not in text
    assert "LeagueTeamDirectoryService" not in text


def test_get_league_teams_route(storage) -> None:
    _store_roster(storage, [("alpha", 76), ("solo", 0)])
    planets = _Profiles({"alpha": PROFILE_76})
    from api.app import app
    from api.routers.games import get_planets_client

    app.dependency_overrides[get_planets_client] = lambda: planets
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/games/628580/league-teams")
        missing = client.get("/v1/games/999999/league-teams")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"teams": [{"id": 76, "name": SHADOWHAWKS}]}
    assert missing.status_code == 404
    assert planets.calls == ["alpha"]
