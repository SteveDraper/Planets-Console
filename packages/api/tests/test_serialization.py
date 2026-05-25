"""Tests for serialization codecs (dacite round-trips, enum handling, nested objects)."""

import copy
import json
from pathlib import Path

import pytest
from api.models.enums import GameStatus, MessageType, NativeType
from api.models.ship import ShipHistory
from api.serialization.codecs import (
    dataclass_deserialization_detail,
    describe_dacite_error,
)
from api.serialization.game import game_info_from_json, game_info_to_json
from api.serialization.turn import turn_info_from_json, turn_info_to_json
from dacite.exceptions import DaciteError, MissingValueError, WrongTypeError

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


class TestDescribeDaciteError:
    def test_missing_value(self):
        err = MissingValueError("settings.allplanetsvisible")
        assert describe_dacite_error(err) == "missing required field 'settings.allplanetsvisible'"

    def test_wrong_type(self, turn_sample_data):
        data = copy.deepcopy(turn_sample_data)
        data["settings"]["id"] = "not-int"
        try:
            turn_info_from_json(data)
        except WrongTypeError as err:
            detail = describe_dacite_error(err)
        else:
            raise AssertionError("expected WrongTypeError")
        assert "settings.id" in detail
        assert "int" in detail
        assert "str" in detail

    def test_dataclass_deserialization_detail_includes_prefix(self):
        err = MissingValueError("player.username")
        assert dataclass_deserialization_detail("Turn payload invalid", err) == (
            "Turn payload invalid (missing required field 'player.username')."
        )


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

    def test_historical_settings_backfilled_from_defaults(self, turn_sample_data):
        """Older turn snapshots may omit newer settings keys; fill from game info defaults."""
        historical = copy.deepcopy(turn_sample_data)
        defaults = copy.deepcopy(turn_sample_data["settings"])
        for key in (
            "allplanetsvisible",
            "planetownershipvisible",
            "starbasesvisible",
            "shipsatplanetsvisible",
            "spectatormode",
        ):
            del historical["settings"][key]

        with pytest.raises(DaciteError):
            turn_info_from_json(historical)

        ti = turn_info_from_json(historical, settings_defaults=defaults)
        assert ti.settings.allplanetsvisible is defaults["allplanetsvisible"]
        assert ti.settings.spectatormode is defaults["spectatormode"]

    def test_turn_info_from_json_does_not_mutate_input(self, turn_sample_data):
        data = copy.deepcopy(turn_sample_data)
        before = copy.deepcopy(data)
        turn_info_from_json(data, settings_defaults=data["settings"])
        assert data == before

    def test_turn_info_from_json_without_defaults_does_not_mutate_input(self, turn_sample_data):
        data = copy.deepcopy(turn_sample_data)
        before = copy.deepcopy(data)
        turn_info_from_json(data)
        assert data == before

    def test_turn_info_from_json_skips_copy_when_settings_already_complete(
        self, turn_sample_data, monkeypatch
    ):
        deepcopy_calls: list[object] = []
        original_deepcopy = copy.deepcopy

        def counting_deepcopy(value):
            deepcopy_calls.append(value)
            return original_deepcopy(value)

        monkeypatch.setattr("api.serialization.turn.copy.deepcopy", counting_deepcopy)
        turn_info_from_json(turn_sample_data, settings_defaults=turn_sample_data["settings"])
        assert deepcopy_calls == []


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
        assert gi.yearfrom == 166
        assert gi.yearto == 277

    def test_yearfrom_yearto_string_coercion(self, game_info_sample_data):
        data = copy.deepcopy(game_info_sample_data)
        data["yearfrom"] = "0180"
        data["yearto"] = "0277"
        gi = game_info_from_json(data)
        assert gi.yearfrom == 180
        assert gi.yearto == 277

    def test_yearto_question_mark_unknown(self, game_info_sample_data):
        data = copy.deepcopy(game_info_sample_data)
        data["yearto"] = "?"
        gi = game_info_from_json(data)
        assert gi.yearto is None

    def test_game_info_from_json_does_not_mutate_input(self, game_info_sample_data):
        data = copy.deepcopy(game_info_sample_data)
        data["yearfrom"] = "0180"
        before = copy.deepcopy(data)
        _ = game_info_from_json(data)
        assert data == before
