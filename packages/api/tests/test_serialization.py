"""Tests for serialization codecs (dacite round-trips, enum handling, nested objects)."""

import json
from pathlib import Path

import pytest
from api.models.enums import GameStatus, MessageType, NativeType
from api.models.ship import ShipHistory
from api.serialization.game import game_info_from_json, game_info_to_json
from api.serialization.turn import turn_info_from_json, turn_info_to_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def turn_sample_data():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return json.load(f)


@pytest.fixture
def game_info_sample_data():
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        return json.load(f)


class TestTurnInfoSerialization:
    def test_deserialize(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        assert ti.game.id == 628580
        assert ti.settings.turn == 111
        assert len(ti.planets) > 0
        assert len(ti.ships) > 0

    def test_round_trip(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        out = turn_info_to_json(ti)
        ti2 = turn_info_from_json(out)
        assert ti2.game.id == ti.game.id
        assert ti2.settings.name == ti.settings.name
        assert len(ti2.planets) == len(ti.planets)
        assert len(ti2.ships) == len(ti.ships)

    def test_enum_deserialization_game_status(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        assert ti.game.status == GameStatus.FINISHED
        assert isinstance(ti.game.status, GameStatus)

    def test_enum_deserialization_native_type(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        for planet in ti.planets:
            assert isinstance(planet.nativetype, NativeType)

    def test_enum_deserialization_message_type(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        for msg in ti.messages:
            assert isinstance(msg.messagetype, MessageType)

    def test_enum_serialization_outputs_int(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        out = turn_info_to_json(ti)
        assert isinstance(out["game"]["status"], int)
        assert out["game"]["status"] == 3

    def test_nested_ship_history(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        ships_with_history = [s for s in ti.ships if s.history]
        assert len(ships_with_history) > 0
        h = ships_with_history[0].history[0]
        assert isinstance(h, ShipHistory)
        assert isinstance(h.x, int)
        assert isinstance(h.y, int)

    def test_nested_vcr_sides(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        assert len(ti.vcrs) > 0
        vcr = ti.vcrs[0]
        assert vcr.left.name
        assert vcr.right.name
        assert isinstance(vcr.left.hasstarbase, bool)

    def test_unknown_message_type_maps_to_sentinel(self, turn_sample_data):
        """Unrecognised messagetype ints deserialize to MessageType.UNKNOWN."""
        turn_sample_data["messages"][0]["messagetype"] = 999
        ti = turn_info_from_json(turn_sample_data)
        assert ti.messages[0].messagetype is MessageType.UNKNOWN
        assert ti.messages[0].messagetype == -1

    def test_unknown_native_type_maps_to_sentinel(self, turn_sample_data):
        turn_sample_data["planets"][0]["nativetype"] = 42
        ti = turn_info_from_json(turn_sample_data)
        assert ti.planets[0].nativetype is NativeType.UNKNOWN

    def test_unknown_game_status_maps_to_sentinel(self, turn_sample_data):
        turn_sample_data["game"]["status"] = 77
        ti = turn_info_from_json(turn_sample_data)
        assert ti.game.status is GameStatus.UNKNOWN

    def test_unknown_enum_round_trips_as_sentinel_value(self, turn_sample_data):
        """UNKNOWN sentinel serializes as -1 in JSON output."""
        turn_sample_data["messages"][0]["messagetype"] = 999
        ti = turn_info_from_json(turn_sample_data)
        out = turn_info_to_json(ti)
        assert out["messages"][0]["messagetype"] == -1

    def test_extra_keys_tolerated(self, turn_sample_data):
        """Payloads with unknown keys should not cause errors (strict=False)."""
        turn_sample_data["unknown_future_field"] = "value"
        turn_sample_data["game"]["some_new_field"] = 42
        ti = turn_info_from_json(turn_sample_data)
        assert ti.game.id == 628580

    def test_empty_collections(self, turn_sample_data):
        assert turn_sample_data["nebulas"] == []
        ti = turn_info_from_json(turn_sample_data)
        assert ti.nebulas == []
        assert ti.blackholes == []
        assert ti.wormholes == []

    def test_badgechange_bool(self, turn_sample_data):
        ti = turn_info_from_json(turn_sample_data)
        assert isinstance(ti.badgechange, bool)


class TestGameInfoSerialization:
    def test_deserialize(self, game_info_sample_data):
        gi = game_info_from_json(game_info_sample_data)
        assert gi.game.id == 628580
        assert gi.game.name == "Serada 9 Sector"
        assert len(gi.players) > 0

    def test_round_trip(self, game_info_sample_data):
        gi = game_info_from_json(game_info_sample_data)
        out = game_info_to_json(gi)
        gi2 = game_info_from_json(out)
        assert gi2.game.id == gi.game.id
        assert gi2.schedule == gi.schedule

    def test_enum_deserialization(self, game_info_sample_data):
        gi = game_info_from_json(game_info_sample_data)
        assert isinstance(gi.game.status, GameStatus)

    def test_game_info_fields(self, game_info_sample_data):
        gi = game_info_from_json(game_info_sample_data)
        assert gi.schedule
        assert gi.timetohost
        assert gi.wincondition
        assert isinstance(gi.yearfrom, int)
        assert isinstance(gi.yearto, int)
