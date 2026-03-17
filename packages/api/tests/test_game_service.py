"""Tests for the GameService."""

import json
from pathlib import Path

import pytest
from api.errors import NotFoundError, ValidationError
from api.models.game import GameInfo, TurnInfo
from api.services.game_service import GameService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def seeded_backend():
    """Return a MemoryAssetBackend pre-seeded with the sample assets."""
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/turns/111", json.load(f))
    return backend


@pytest.fixture
def service(seeded_backend):
    return GameService(seeded_backend)


class TestGetGameInfo:
    def test_returns_game_info(self, service):
        gi = service.get_game_info(628580)
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580
        assert gi.game.name == "Serada 9 Sector"

    def test_players_populated(self, service):
        gi = service.get_game_info(628580)
        assert len(gi.players) > 0
        assert gi.players[0].username

    def test_not_found_raises(self, service):
        with pytest.raises(NotFoundError):
            service.get_game_info(999999)


class TestGetTurnInfo:
    def test_returns_turn_info(self, service):
        ti = service.get_turn_info(628580, 111)
        assert isinstance(ti, TurnInfo)
        assert ti.settings.turn == 111

    def test_planets_populated(self, service):
        ti = service.get_turn_info(628580, 111)
        assert len(ti.planets) > 0

    def test_ships_populated(self, service):
        ti = service.get_turn_info(628580, 111)
        assert len(ti.ships) > 0

    def test_not_found_game(self, service):
        with pytest.raises(NotFoundError):
            service.get_turn_info(999999, 111)

    def test_not_found_turn(self, service):
        with pytest.raises(NotFoundError):
            service.get_turn_info(628580, 999)


class TestMalformedStoreData:
    def test_game_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/info", ["not", "a", "dict"])
        svc = GameService(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            svc.get_game_info(1)

    def test_turn_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/turns/1", "just a string")
        svc = GameService(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            svc.get_turn_info(1, 1)
