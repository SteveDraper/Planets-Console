"""Tests for inference prior mining observation extraction."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ANY_PRIOR_KEY,
)
from api.analytics.military_score_inference.prior_mining.observations import (
    _extract_player_host_turn,
    _ship_matches_starbase_order,
)
from api.models.game import TurnInfo
from api.models.player import Score
from api.models.ship import Ship
from api.models.starbase import Starbase
from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.fixtures import load_turn_fixture

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _score_for_player(turn: TurnInfo, player_id: int) -> Score:
    score = next(row for row in turn.scores if row.ownerid == player_id)
    return score


def test_ship_matches_starbase_order_requires_exact_fitted_spec():
    starbase = Starbase(
        id=1,
        defense=0,
        builtdefense=0,
        damage=0,
        enginetechlevel=0,
        hulltechlevel=0,
        beamtechlevel=0,
        torptechlevel=0,
        hulltechup=0,
        enginetechup=0,
        beamtechup=0,
        torptechup=0,
        fighters=0,
        builtfighters=0,
        shipmission=0,
        mission=0,
        mission1target=0,
        planetid=100,
        raceid=0,
        targetshipid=0,
        buildbeamid=3,
        buildengineid=9,
        buildtorpedoid=6,
        buildhullid=13,
        buildbeamcount=8,
        buildtorpcount=6,
        isbuilding=True,
        starbasetype=0,
        infoturn=2,
        readystatus=0,
    )
    ship = Ship(
        id=99,
        friendlycode="xxx",
        name="test",
        warp=0,
        x=10,
        y=20,
        beams=8,
        bays=0,
        torps=6,
        mission=0,
        mission1target=0,
        mission2target=0,
        enemy=0,
        damage=0,
        crew=0,
        clans=0,
        neutronium=0,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        supplies=0,
        ammo=0,
        megacredits=0,
        transferclans=0,
        transferneutronium=0,
        transferduranium=0,
        transfertritanium=0,
        transfermolybdenum=0,
        transfersupplies=0,
        transferammo=0,
        transfermegacredits=0,
        transfertargetid=0,
        transfertargettype=0,
        targetx=0,
        targety=0,
        mass=0,
        heading=0,
        turn=3,
        turnkilled=0,
        beamid=3,
        engineid=9,
        hullid=13,
        ownerid=1,
        torpedoid=6,
        experience=0,
        infoturn=3,
        podhullid=0,
        podcargo=0,
        goal=0,
        goaltarget=0,
        goaltarget2=0,
    )
    assert _ship_matches_starbase_order(ship, starbase)
    assert not _ship_matches_starbase_order(replace(ship, beams=7), starbase)


def test_extract_validated_ship_build_from_synthetic_turn_pair():
    prior_turn = load_turn_fixture("628580/1/turns/2.json")
    score_turn = load_turn_fixture("628580/1/turns/3.json")

    template_planet = turn_info_from_json(
        json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8")),
        settings_defaults=json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))[
            "settings"
        ],
    ).planets[0]
    planet = replace(template_planet, id=272, x=1813, y=2810, ownerid=1)
    prior_turn = replace(prior_turn, planets=[*prior_turn.planets, planet])

    extraction = _extract_player_host_turn(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
        score=_score_for_player(score_turn, 1),
        race_id=1,
    )

    assert len(extraction.ship_builds) == 1
    build = extraction.ship_builds[0]
    assert build.hull_id == 13
    assert build.engine_id == 9
    assert build.beam_count == 8
    assert build.launcher_count == 6
    assert extraction.ship_build_validation_drops == 0


def test_aggregate_histogram_includes_zero_bins():
    prior_turn = load_turn_fixture("628580/1/turns/51.json")
    score_turn = load_turn_fixture("628580/1/turns/52.json")
    extraction = _extract_player_host_turn(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
        score=_score_for_player(score_turn, 1),
        race_id=1,
    )
    assert extraction.aggregate_deltas["planet_defense_posts_added_total"] == 0
    assert extraction.aggregate_deltas[SHIP_TORPS_LOADED_ANY_PRIOR_KEY] == sum(
        extraction.aggregate_deltas[f"ship_torps_loaded_{torp.id}"] for torp in prior_turn.torpedos
    )
    assert "ship_fighters_added_total" in extraction.aggregate_deltas
    assert extraction.aggregate_deltas["fighters_starbase_to_ship"] in (0, 1)
