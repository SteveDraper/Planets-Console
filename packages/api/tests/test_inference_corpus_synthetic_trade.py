"""Synthetic post-accel fixture: two disjoint public-scoreboard trades."""

from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.accelerated_start import needs_accelerated_backfill
from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    TRADE_ACTION_PREFIX,
    public_scoreboard_rows_from_scores,
)
from api.concepts.accelerated_scoreboard import accelerated_inference_segments
from api.concepts.ship_build_military import ship_build_military_score_delta_2x
from api.models.game import TurnInfo
from api.models.ship import Ship

from tests.inference_corpus.fixtures import load_turn_fixture
from tests.inference_corpus.manifest import load_manifest
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.run import run_manifest_case

SYNTHETIC_PRIOR_PATH = "900001/1/turns/10.json"
SYNTHETIC_SCORE_PATH = "900001/1/turns/11.json"
MILITARY_SWAP_CASE_ID = "900001-p1-host10"
CLASS_FLIP_CASE_ID = "900001-p3-host10"


def _load_synthetic_pair() -> tuple[TurnInfo, TurnInfo]:
    return load_turn_fixture(SYNTHETIC_PRIOR_PATH), load_turn_fixture(SYNTHETIC_SCORE_PATH)


def _ship_military_1x(ship: Ship, turn: TurnInfo) -> int:
    hulls = {hull.id: hull for hull in turn.hulls}
    engines = {engine.id: engine for engine in turn.engines}
    beams = {beam.id: beam for beam in turn.beams}
    hull = hulls[ship.hullid]
    engine = engines[ship.engineid]
    beam = beams.get(ship.beamid) if ship.beamid else None
    delta_2x = ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        None,
        beam_count=ship.beams,
        launcher_count=ship.torps,
    )
    return delta_2x // 2


def _prior_fleet_records_for(player_id: int, prior_turn: TurnInfo) -> tuple[FleetShipRecord, ...]:
    records: list[FleetShipRecord] = []
    for ship in prior_turn.ships:
        if ship.ownerid != player_id:
            continue
        records.append(
            FleetShipRecord(
                record_id=f"ship-{ship.id}",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldKnown(ship.id),
                    hull=FleetFieldKnown(ship.hullid),
                    engine=FleetFieldKnown(ship.engineid),
                    beams=FleetFieldKnown(ship.beamid),
                    launchers=FleetFieldKnown(ship.torpedoid if ship.torps else 0),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(
                        combo_id=f"prior-{ship.id}",
                        hull_id=ship.hullid,
                        engine_id=ship.engineid,
                        beam_id=ship.beamid or None,
                        beam_count=ship.beams,
                        launcher_count=ship.torps,
                    )
                ],
            )
        )
    return tuple(records)


def _pairing_for_player(player_id: int, score_turn: TurnInfo):
    score = next(row for row in score_turn.scores if row.ownerid == player_id)
    observation = build_inference_observation(score, score_turn)
    pairing = classify_public_scoreboard_pairing(
        public_scoreboard_row_from_observation(observation),
        public_scoreboard_rows_from_scores(score_turn.scores, this_player_id=player_id),
    )
    return observation, pairing


def test_synthetic_trade_fixture_does_not_trigger_accelerated_backfill():
    _, score_turn = _load_synthetic_pair()
    assert score_turn.settings.acceleratedturns == 3
    assert score_turn.settings.turn == 11
    assert needs_accelerated_backfill(score_turn.settings.turn, score_turn.settings) is False
    idle = next(row for row in score_turn.scores if row.ownerid == 5)
    assert accelerated_inference_segments(idle, score_turn) is None


def test_synthetic_trade_scoreboard_uses_construction_military_helpers():
    prior_turn, score_turn = _load_synthetic_pair()
    prior_by_id = {ship.id: ship for ship in prior_turn.ships}
    military_by_ship = {
        ship_id: _ship_military_1x(ship, prior_turn) for ship_id, ship in prior_by_id.items()
    }
    assert military_by_ship[103] == 0
    assert abs(2 * (military_by_ship[102] - military_by_ship[101])) > 2

    expected_change = {
        1: {
            "shipchange": 0,
            "freighterchange": 0,
            "militarychange": military_by_ship[102] - military_by_ship[101],
            "militaryscore": military_by_ship[102],
            "capitalships": 1,
            "freighters": 0,
        },
        2: {
            "shipchange": 0,
            "freighterchange": 0,
            "militarychange": military_by_ship[101] - military_by_ship[102],
            "militaryscore": military_by_ship[101],
            "capitalships": 1,
            "freighters": 0,
        },
        3: {
            "shipchange": 1,
            "freighterchange": -1,
            "militarychange": military_by_ship[104] - military_by_ship[103],
            "militaryscore": military_by_ship[104],
            "capitalships": 1,
            "freighters": 0,
        },
        4: {
            "shipchange": -1,
            "freighterchange": 1,
            "militarychange": military_by_ship[103] - military_by_ship[104],
            "militaryscore": military_by_ship[103],
            "capitalships": 0,
            "freighters": 1,
        },
        5: {
            "shipchange": 0,
            "freighterchange": 0,
            "militarychange": 0,
            "militaryscore": 0,
            "capitalships": 0,
            "freighters": 0,
        },
    }
    for row in score_turn.scores:
        expected = expected_change[row.ownerid]
        assert row.shipchange == expected["shipchange"]
        assert row.freighterchange == expected["freighterchange"]
        assert row.militarychange == expected["militarychange"]
        assert row.militaryscore == expected["militaryscore"]
        assert row.capitalships == expected["capitalships"]
        assert row.freighters == expected["freighters"]


def test_synthetic_trade_pairing_classifies_both_disjoint_pairs():
    _, score_turn = _load_synthetic_pair()

    swap_left, pairing_1 = _pairing_for_player(1, score_turn)
    assert swap_left.warship_delta == 0
    assert swap_left.freighter_delta == 0
    assert [match.family for match in pairing_1.matches] == ["trade"]
    assert pairing_1.matches[0].counterparty_player_id == 2

    _, pairing_2 = _pairing_for_player(2, score_turn)
    assert [match.family for match in pairing_2.matches] == ["trade"]
    assert pairing_2.matches[0].counterparty_player_id == 1

    flip_left, pairing_3 = _pairing_for_player(3, score_turn)
    assert flip_left.warship_delta == 1
    assert flip_left.freighter_delta == -1
    assert [match.family for match in pairing_3.matches] == ["trade"]
    assert pairing_3.matches[0].counterparty_player_id == 4

    _, pairing_4 = _pairing_for_player(4, score_turn)
    assert [match.family for match in pairing_4.matches] == ["trade"]
    assert pairing_4.matches[0].counterparty_player_id == 3

    _, pairing_idle = _pairing_for_player(5, score_turn)
    assert pairing_idle.matches == ()


def test_synthetic_trade_catalog_emits_trade_actions_for_both_pairs():
    prior_turn, score_turn = _load_synthetic_pair()

    swap_score = next(row for row in score_turn.scores if row.ownerid == 1)
    swap_observation = build_inference_observation(swap_score, score_turn)
    swap_catalog = build_action_catalog_from_turn(
        swap_observation,
        score_turn,
        prior_fleet_records=_prior_fleet_records_for(1, prior_turn),
    )
    swap_trade_ids = [
        action.id
        for action in swap_catalog.aggregate_actions
        if action.id.startswith(TRADE_ACTION_PREFIX)
    ]
    assert swap_trade_ids == [
        f"{TRADE_ACTION_PREFIX}warship:with:2:swap:{swap_observation.military_delta_2x}"
    ]

    flip_score = next(row for row in score_turn.scores if row.ownerid == 3)
    flip_observation = build_inference_observation(flip_score, score_turn)
    flip_catalog = build_action_catalog_from_turn(
        flip_observation,
        score_turn,
        prior_fleet_records=_prior_fleet_records_for(3, prior_turn),
    )
    flip_trade_ids = [
        action.id
        for action in flip_catalog.aggregate_actions
        if action.id.startswith(TRADE_ACTION_PREFIX)
    ]
    flip_prefix = f"{TRADE_ACTION_PREFIX}freighter:with:4:"
    assert any(action_id.startswith(flip_prefix) for action_id in flip_trade_ids)


def test_synthetic_trade_adjunct_rows_skipped_by_default():
    _, cases = load_manifest()
    for case_id in (MILITARY_SWAP_CASE_ID, CLASS_FLIP_CASE_ID):
        case = next(row for row in cases if row.id == case_id)
        result = run_manifest_case(case)
        assert result.outcome == CaseOutcome.SKIPPED_COMPLEXITY
        assert result.skip_reason == "adjunct_disabled"
        assert result.complexity == "adjunct"
