"""Tests for ship inventory semantics in inference corpus ground truth."""

import json

from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.ground_truth import describe_inventory_activity
from tests.inference_corpus.manifest import FIXTURES_ROOT
from tests.inference_corpus.ship_inventory import (
    describe_new_ship_build,
    fighter_load_delta,
    loaded_fighter_count,
    loaded_torpedo_count,
    new_owned_ships,
    torpedo_load_delta_by_type,
)


def _turn_pair():
    settings = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    with open(FIXTURES_ROOT / "628580/1/turns/2.json") as handle:
        prior_turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    with open(FIXTURES_ROOT / "628580/1/turns/3.json") as handle:
        score_turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    return prior_turn, score_turn


def test_missouri_ammo_is_loaded_torpedoes_not_fighters():
    _, score_turn = _turn_pair()
    new_ship = new_owned_ships(_turn_pair()[0], score_turn, player_id=1)[0]
    hull = next(h for h in score_turn.hulls if h.id == new_ship.hullid)

    assert new_ship.ammo == 40
    assert new_ship.bays == 0
    assert loaded_fighter_count(new_ship, hull) == 0
    assert loaded_torpedo_count(new_ship, hull) == 40


def test_fleet_fighter_delta_excludes_torp_ship_ammo():
    prior_turn, score_turn = _turn_pair()
    assert fighter_load_delta(prior_turn, score_turn, player_id=1) == 0


def test_torp_delta_uses_ammo_not_launcher_count():
    prior_turn, score_turn = _turn_pair()
    new_ids = frozenset(ship.id for ship in new_owned_ships(prior_turn, score_turn, 1))
    deltas = torpedo_load_delta_by_type(
        prior_turn,
        score_turn,
        player_id=1,
        exclude_ship_ids=new_ids,
    )
    assert deltas == {}
    full_deltas = torpedo_load_delta_by_type(prior_turn, score_turn, player_id=1)
    assert full_deltas.get(6) == 40


def test_describe_new_ship_build_includes_components():
    prior_turn, score_turn = _turn_pair()
    new_ship = new_owned_ships(prior_turn, score_turn, player_id=1)[0]
    line = describe_new_ship_build(new_ship, score_turn)

    assert "Missouri Class Battleship" in line
    assert "2x Transwarp Drive" in line
    assert "8x Plasma Bolt" in line
    assert "6x Mark 4 Photon launcher" in line
    assert "loaded 40x Mark 4 Photon" in line
    assert "fighter" not in line.lower()


def test_describe_inventory_activity_missouri_host_turn_2():
    prior_turn, score_turn = _turn_pair()
    summary = describe_inventory_activity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
    )
    assert "Transwarp Drive" in summary
    assert "loaded 40x Mark 4 Photon" in summary
    assert "ship fighters" not in summary
    assert "ship torps +6" not in summary
