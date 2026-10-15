"""Incoming warship transfers use the minimum legal hull fill, not a torpedo fit."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.types import FleetFieldKnown, FleetShipRecord, FleetShipRecordFields
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.incoming_warship_floor import (
    fitting_incoming_warship_transfers,
)
from api.analytics.military_score_inference.inference_api_payload import (
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.models import CandidateAction
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.ship_first_overshoot import ShipFirstOvershootPlan
from api.analytics.military_score_inference.solver import STATUS_MINE_SCORE_RESIDUAL
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.models.components import Beam, Engine, Hull

from tests.fixtures.military_score_inference import _observation


def _hull(*, hull_id: int, beams: int, fighter_bays: int = 0) -> Hull:
    return Hull(
        id=hull_id,
        name=f"hull-{hull_id}",
        tritanium=33,
        duranium=15,
        molybdenum=5,
        fueltank=160,
        crew=35,
        engines=1,
        mass=55,
        techlevel=1,
        cargo=20,
        fighterbays=fighter_bays,
        launchers=0,
        beams=beams,
        cancloak=False,
        cost=40,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def _tables() -> tuple[dict[int, Hull], dict[int, Engine], dict[int, Beam], dict]:
    hulls = {
        24: _hull(hull_id=24, beams=2),
        15: _hull(hull_id=15, beams=0),
    }
    engines = {
        1: Engine(
            id=1,
            name="Stardrive 1",
            cost=5,
            tritanium=1,
            duranium=1,
            molybdenum=1,
            techlevel=1,
            warp1=50,
            warp2=40,
            warp3=30,
            warp4=20,
            warp5=10,
            warp6=0,
            warp7=0,
            warp8=0,
            warp9=0,
        )
    }
    beams = {
        1: Beam(
            id=1,
            name="Laser",
            cost=1,
            tritanium=1,
            duranium=0,
            molybdenum=0,
            mass=1,
            techlevel=1,
            crewkill=10,
            damage=3,
        )
    }
    return hulls, engines, beams, {}


def _record(hull_id: int) -> FleetShipRecord:
    return FleetShipRecord(
        record_id=f"ship-{hull_id}",
        fields=FleetShipRecordFields(hull=FleetFieldKnown(value=hull_id)),
    )


def _action(player_id: int) -> CandidateAction:
    return CandidateAction(
        id=f"acquired:warship:from:{player_id}",
        label=f"Acquired warship from player {player_id}",
        score_delta_2x=0,
        warship_delta=1,
        counterparty_player_id=player_id,
        upper_bound=1,
    )


def _transfers(**overrides: object):
    hulls, engines, beams, torpedos = _tables()
    kwargs = {
        "military_delta_2x": 2000,
        "warship_delta": 1,
        "actions": (_action(16),),
        "records_for_player": lambda player_id: (_record(24),) if player_id == 16 else (),
        "hulls_by_id": hulls,
        "engines_by_id": engines,
        "beams_by_id": beams,
        "torpedos_by_id": torpedos,
        "max_solutions": 20,
    }
    kwargs.update(overrides)
    return fitting_incoming_warship_transfers(**kwargs)


def test_fitting_donor_emits_one_transfer_without_torpedoes() -> None:
    solutions = _transfers()
    assert solutions is not None
    assert len(solutions) == 1
    solution = solutions[0]
    assert solution.ship_builds == ()
    assert solution.ship_first_family == "mine_overshoot"
    assert [action.action_id for action in solution.actions] == ["acquired:warship:from:16"]
    assert solution.actions[0].count == 1


def test_rise_below_every_hull_floor_keeps_the_search() -> None:
    assert _transfers(military_delta_2x=1) is None


def test_freighter_hull_does_not_count_as_a_warship_floor() -> None:
    assert _transfers(records_for_player=lambda _player_id: (_record(15),)) is None


def test_missing_donor_ledger_keeps_the_search() -> None:
    assert _transfers(records_for_player=lambda _player_id: ()) is None
    assert _transfers(records_for_player=None) is None


def test_floor_row_finalizes_as_mine_residual_without_a_solve(sample_turn, monkeypatch) -> None:
    def fail_solve(*_args, **_kwargs):
        raise AssertionError("hull floor path must not call the solver")

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        fail_solve,
    )

    def catalog_from_turn(_observation, _turn, **kwargs):
        policy_step = kwargs.get("policy_step")
        return ActionCatalog(
            aggregate_actions=(_action(16),),
            ship_build_combos=(),
            probability_buckets_by_action_id={},
            policy_step_id=policy_step.id if policy_step is not None else "",
            policy_step_index=kwargs.get("policy_step_index", 0),
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        catalog_from_turn,
    )
    hulls, engines, beams, torpedos = _tables()
    turn = replace(
        sample_turn,
        hulls=list(hulls.values()),
        engines=list(engines.values()),
        beams=list(beams.values()),
        torpedos=list(torpedos.values()),
    )
    observation = _observation(military_delta_2x=2000, warship_delta=1)
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(None)[:1]),
        ship_first_overshoot=ShipFirstOvershootPlan(
            mode="overshoot_only",
            cap_2x=4000,
            overshoot_window_empty=False,
        ),
        load_counterparty_fleet=lambda player_id: (_record(24),) if player_id == 16 else (),
    )
    run_policy_ladder_tier_step(state, observation, turn, time_limit_seconds=1.0)
    result, catalog, problem, _attempted, steps = finalize_policy_ladder_result(
        state,
        observation,
        turn,
    )
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert problem is not None
    assert problem.military_overshoot_cap_2x == 4000
    assert [action.action_id for action in result.solutions[0].actions] == [
        "acquired:warship:from:16"
    ]
    assert catalog is not None
    payload = inference_result_to_api_payload(
        result,
        catalog,
        observation,
        turn,
        problem,
        step_diagnostics=steps,
    )
    assert payload["summary"] == "Mine-score leftover (-1000)"
    assert payload["status"] == STATUS_MINE_SCORE_RESIDUAL
    emissions = payload["tierEmissions"]
    assert isinstance(emissions, list) and emissions
    assert emissions[0]["ladderEarlyStopReason"] == "incoming_warship_floor"
    assert emissions[0]["timeLimited"] is False
