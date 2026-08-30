"""Post-unsat unknown military ship and residual freighter placeholders."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_api_payload import inference_api_payload
from api.analytics.military_score_inference.models import InferenceProblem, InferenceResult
from api.analytics.military_score_inference.post_unsat_placeholders import (
    UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
    explode_placeholder_to_unit_payloads,
    post_unsat_placeholders,
    post_unsat_placeholders_from_turn,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.concepts.hulls import (
    GENERIC_FREIGHTER_SENTINEL_HULL_ID,
    UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
)
from api.concepts.ship_build_military import is_military_hull, warship_construction_envelope_2x
from api.models.components import Beam, Engine, Hull, Torpedo
from api.transport.inference_stream import stream_inference_ndjson
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

from tests.fixtures.military_score_inference import _observation

# Independent AutoScore 2x literals for the catalog below (not copied from production).
# Scout min: hull 40/10 + cheap engine 5/3 + 1 cheap beam 1/1
#   mc=46 minerals=14 -> 2 * (46 + 5*14) = 232
# Scout max: hull 40/10 + expensive engine 300/24 + 2 expensive beams 50/10 each
#   mc=440 minerals=54 -> 2 * (440 + 5*54) = 1420
# Carrier min: hull 100/30 + 2 cheap engines 5/3 (0 weapons, fighter bays)
#   mc=110 minerals=36 -> 2 * (110 + 5*36) = 580
# Carrier max: hull 100/30 + 2 expensive engines 300/24
#   mc=700 minerals=78 -> 2 * (700 + 5*78) = 2180
_SCOUT_MIN_2X = 232
_SCOUT_MAX_2X = 1420
_CARRIER_MIN_2X = 580
_CARRIER_MAX_2X = 2180


def _hull(
    *,
    hull_id: int,
    name: str,
    cost: int,
    tritanium: int,
    duranium: int,
    molybdenum: int,
    engines: int,
    beams: int = 0,
    launchers: int = 0,
    fighterbays: int = 0,
) -> Hull:
    return Hull(
        id=hull_id,
        name=name,
        tritanium=tritanium,
        duranium=duranium,
        molybdenum=molybdenum,
        fueltank=100,
        crew=10,
        engines=engines,
        mass=50,
        techlevel=1,
        cargo=20,
        fighterbays=fighterbays,
        launchers=launchers,
        beams=beams,
        cancloak=False,
        cost=cost,
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


def _engine(*, engine_id: int, name: str, cost: int, minerals: int) -> Engine:
    return Engine(
        id=engine_id,
        name=name,
        cost=cost,
        tritanium=minerals,
        duranium=0,
        molybdenum=0,
        techlevel=1,
        warp1=0,
        warp2=0,
        warp3=0,
        warp4=0,
        warp5=0,
        warp6=0,
        warp7=0,
        warp8=0,
        warp9=0,
    )


def _beam(*, beam_id: int, name: str, cost: int, minerals: int) -> Beam:
    return Beam(
        id=beam_id,
        name=name,
        cost=cost,
        tritanium=minerals,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=1,
        crewkill=1,
        damage=1,
    )


def _torpedo(*, torp_id: int, name: str, launchercost: int, minerals: int) -> Torpedo:
    return Torpedo(
        id=torp_id,
        fullid=torp_id,
        name=name,
        torpedocost=1,
        launchercost=launchercost,
        tritanium=minerals,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=1,
        crewkill=1,
        damage=1,
        combatrange=1,
    )


def _catalog_parts():
    scout = _hull(
        hull_id=1,
        name="Scout",
        cost=40,
        tritanium=10,
        duranium=0,
        molybdenum=0,
        engines=1,
        beams=2,
    )
    carrier = _hull(
        hull_id=2,
        name="Carrier",
        cost=100,
        tritanium=30,
        duranium=0,
        molybdenum=0,
        engines=2,
        fighterbays=5,
    )
    freighter = _hull(
        hull_id=15,
        name="Freighter",
        cost=10,
        tritanium=2,
        duranium=2,
        molybdenum=3,
        engines=1,
    )
    cheap_engine = _engine(engine_id=1, name="StarDrive 1", cost=5, minerals=3)
    expensive_engine = _engine(engine_id=9, name="Transwarp", cost=300, minerals=24)
    cheap_beam = _beam(beam_id=1, name="Laser", cost=1, minerals=1)
    expensive_beam = _beam(beam_id=10, name="Heavy Phaser", cost=50, minerals=10)
    return {
        "hulls_by_id": {scout.id: scout, carrier.id: carrier, freighter.id: freighter},
        "engines_by_id": {cheap_engine.id: cheap_engine, expensive_engine.id: expensive_engine},
        "beams_by_id": {cheap_beam.id: cheap_beam, expensive_beam.id: expensive_beam},
        "torpedos_by_id": {},
        "buildable_hull_ids": frozenset({scout.id, carrier.id, freighter.id}),
    }


def test_warship_construction_envelope_uses_cheapest_and_most_expensive_legal_fills():
    parts = _catalog_parts()
    envelope = warship_construction_envelope_2x(**parts)
    assert envelope == (_SCOUT_MIN_2X, _CARRIER_MAX_2X)


def test_warship_construction_envelope_carrier_counts_at_zero_beams():
    parts = _catalog_parts()
    parts["buildable_hull_ids"] = frozenset({2})
    envelope = warship_construction_envelope_2x(**parts)
    assert envelope == (_CARRIER_MIN_2X, _CARRIER_MAX_2X)


def test_warship_construction_envelope_is_empty_when_no_legal_warship_hull():
    parts = _catalog_parts()
    parts["buildable_hull_ids"] = frozenset({15})
    assert warship_construction_envelope_2x(**parts) is None


def test_warship_construction_envelope_is_empty_without_engines_for_engine_hulls():
    parts = _catalog_parts()
    parts["engines_by_id"] = {}
    assert warship_construction_envelope_2x(**parts) is None


def test_unknown_military_placeholder_count_is_positive_shipchange_remainder():
    placeholders = post_unsat_placeholders(
        _observation(warship_delta=3, freighter_delta=0, military_delta_2x=40),
        **_catalog_parts(),
    )
    assert len(placeholders) == 1
    military = placeholders[0]
    assert military["id"] == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
    assert military["hullId"] == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
    assert military["count"] == 3
    assert military["militaryScoreDelta2xMin"] == _SCOUT_MIN_2X
    assert military["militaryScoreDelta2xMax"] == _CARRIER_MAX_2X
    assert military["buildSlotUsage"] == 1
    assert "probability_weight" not in military
    assert "probabilityWeight" not in military


@pytest.mark.parametrize("warship_delta", [0, -2])
def test_unknown_military_placeholder_not_emitted_when_remainder_not_positive(warship_delta: int):
    placeholders = post_unsat_placeholders(
        _observation(warship_delta=warship_delta, freighter_delta=0),
        **_catalog_parts(),
    )
    assert placeholders == []


def test_unknown_military_placeholder_not_emitted_when_envelope_empty():
    parts = _catalog_parts()
    parts["buildable_hull_ids"] = frozenset({15})
    placeholders = post_unsat_placeholders(
        _observation(warship_delta=2, freighter_delta=0),
        **parts,
    )
    assert placeholders == []


def test_generic_freighter_placeholder_alongside_unknown_military():
    placeholders = post_unsat_placeholders(
        _observation(warship_delta=2, freighter_delta=4, military_delta_2x=40),
        **_catalog_parts(),
    )
    assert [entry["id"] for entry in placeholders] == [
        UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
        GENERIC_FREIGHTER_COMBO_ID,
    ]
    freighter = placeholders[1]
    assert freighter["hullId"] == GENERIC_FREIGHTER_SENTINEL_HULL_ID
    assert freighter["count"] == 4
    assert freighter["buildSlotUsage"] == 1
    assert "militaryScoreDelta2xMin" not in freighter
    assert "militaryScoreDelta2xMax" not in freighter


def test_leftover_stays_on_row_not_assigned_onto_placeholder_ships():
    leftover_2x = 40
    observation = _observation(warship_delta=2, freighter_delta=1, military_delta_2x=leftover_2x)
    placeholders = post_unsat_placeholders(observation, **_catalog_parts())
    military = placeholders[0]
    assert military["militaryScoreDelta2xMin"] == _SCOUT_MIN_2X
    assert military["militaryScoreDelta2xMax"] == _CARRIER_MAX_2X
    assert leftover_2x != military["militaryScoreDelta2xMin"] * military["count"]
    assert leftover_2x != military["militaryScoreDelta2xMax"] * military["count"]


def _hull_mask(*, effective_enabled_hull_ids: frozenset[int]) -> ResolvedHullCatalogMask:
    return ResolvedHullCatalogMask(
        race_id=0,
        race_name="test",
        master_hull_ids=effective_enabled_hull_ids,
        default_enabled_hull_ids=effective_enabled_hull_ids,
        effective_enabled_hull_ids=effective_enabled_hull_ids,
        has_user_override=True,
    )


def _unknown_military(placeholders: list[dict[str, object]]) -> dict[str, object] | None:
    return next(
        (entry for entry in placeholders if entry["id"] == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID),
        None,
    )


def _sample_observation(sample_turn):
    player_id = next(
        score.ownerid for score in sample_turn.scores if score.ownerid != sample_turn.player.id
    )
    return replace(
        _observation(warship_delta=2, freighter_delta=1, military_delta_2x=22),
        player_id=player_id,
    )


def test_none_resolved_mask_keeps_default_hull_eligibility(sample_turn):
    observation = _sample_observation(sample_turn)
    default_ids = buildable_hull_ids_for_player(sample_turn, observation.player_id)
    default_mask = ResolvedHullCatalogMask(
        race_id=0,
        race_name="test",
        master_hull_ids=default_ids,
        default_enabled_hull_ids=default_ids,
        effective_enabled_hull_ids=default_ids,
        has_user_override=False,
    )
    unmasked = post_unsat_placeholders_from_turn(observation, sample_turn)
    via_none = post_unsat_placeholders_from_turn(observation, sample_turn, resolved_mask=None)
    via_default_mask = post_unsat_placeholders_from_turn(
        observation, sample_turn, resolved_mask=default_mask
    )
    assert unmasked == via_none == via_default_mask


def test_resolved_mask_without_warships_omits_unknown_military(sample_turn):
    observation = _sample_observation(sample_turn)
    baseline = _unknown_military(post_unsat_placeholders_from_turn(observation, sample_turn))
    assert baseline is not None
    omitted = post_unsat_placeholders_from_turn(
        observation,
        sample_turn,
        resolved_mask=_hull_mask(effective_enabled_hull_ids=frozenset()),
    )
    assert _unknown_military(omitted) is None
    assert any(entry["id"] == GENERIC_FREIGHTER_COMBO_ID for entry in omitted)


def test_resolved_mask_excluding_warship_changes_envelope(sample_turn):
    observation = _sample_observation(sample_turn)
    enabled = buildable_hull_ids_for_player(sample_turn, observation.player_id)
    warship_ids = [
        hull.id for hull in sample_turn.hulls if hull.id in enabled and is_military_hull(hull)
    ]
    assert len(warship_ids) > 1
    baseline = _unknown_military(post_unsat_placeholders_from_turn(observation, sample_turn))
    assert baseline is not None
    narrowed = _unknown_military(
        post_unsat_placeholders_from_turn(
            observation,
            sample_turn,
            resolved_mask=_hull_mask(effective_enabled_hull_ids=frozenset({warship_ids[0]})),
        )
    )
    assert narrowed is not None
    assert (
        narrowed["militaryScoreDelta2xMin"] != baseline["militaryScoreDelta2xMin"]
        or narrowed["militaryScoreDelta2xMax"] != baseline["militaryScoreDelta2xMax"]
    )


def test_inference_payload_envelope_respects_resolved_mask(sample_turn):
    from api.analytics.military_score_inference.inference_api_payload import (
        inference_result_to_api_payload,
    )

    catalog = _empty_catalog()
    observation = _sample_observation(sample_turn)
    enabled = buildable_hull_ids_for_player(sample_turn, observation.player_id)
    warship_ids = [
        hull.id for hull in sample_turn.hulls if hull.id in enabled and is_military_hull(hull)
    ]
    assert len(warship_ids) > 1
    problem = InferenceProblem(observation=observation, aggregate_actions=())
    result = InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={})
    unmasked = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    masked = inference_result_to_api_payload(
        result,
        catalog,
        observation,
        sample_turn,
        problem,
        resolved_mask=_hull_mask(effective_enabled_hull_ids=frozenset({warship_ids[0]})),
    )
    unmasked_military = _unknown_military(unmasked["placeholders"])
    masked_military = _unknown_military(masked["placeholders"])
    assert unmasked_military is not None
    assert masked_military is not None
    assert (
        masked_military["militaryScoreDelta2xMin"] != unmasked_military["militaryScoreDelta2xMin"]
        or masked_military["militaryScoreDelta2xMax"]
        != unmasked_military["militaryScoreDelta2xMax"]
    )


def test_explode_placeholder_copies_per_unit_envelope_to_n_unit_payloads():
    placeholder = {
        "id": UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
        "hullId": UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
        "count": 3,
        "militaryScoreDelta2xMin": _SCOUT_MIN_2X,
        "militaryScoreDelta2xMax": _CARRIER_MAX_2X,
        "buildSlotUsage": 1,
    }
    units = explode_placeholder_to_unit_payloads(placeholder)
    assert len(units) == 3
    for unit in units:
        assert unit["count"] == 1
        assert unit["id"] == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
        assert unit["hullId"] == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
        assert unit["militaryScoreDelta2xMin"] == _SCOUT_MIN_2X
        assert unit["militaryScoreDelta2xMax"] == _CARRIER_MAX_2X
        assert unit["buildSlotUsage"] == 1


def test_explode_placeholder_does_not_emit_units_when_count_not_positive():
    assert explode_placeholder_to_unit_payloads({"count": 0, "hullId": -1}) == []
    assert explode_placeholder_to_unit_payloads({"count": -1, "hullId": -1}) == []


def _empty_catalog() -> ActionCatalog:
    return ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )


@pytest.mark.parametrize(
    "status",
    [STATUS_MODERATE_RESIDUAL, STATUS_MINE_SCORE_RESIDUAL, STATUS_NO_EXACT_SOLUTION],
)
def test_residual_payload_fills_placeholders_and_does_not_emit_solutions(
    status: str,
    sample_turn,
):
    from api.analytics.military_score_inference.inference_api_payload import (
        inference_result_to_api_payload,
    )

    catalog = _empty_catalog()
    player_id = next(
        score.ownerid for score in sample_turn.scores if score.ownerid != sample_turn.player.id
    )
    observation = replace(
        _observation(warship_delta=2, freighter_delta=1, military_delta_2x=22),
        player_id=player_id,
    )
    problem = InferenceProblem(observation=observation, aggregate_actions=())
    result = InferenceResult(status=status, solutions=(), diagnostics={})
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    wire = inference_api_payload_to_wire_complete(payload)
    events = [json.loads(line) for line in stream_inference_ndjson(lambda: iter([wire]))]

    assert payload["solutions"] == []
    assert payload["solutionCount"] == 0
    assert payload["unexplainedMilitaryDelta2x"] == 22
    ids = [entry["id"] for entry in payload["placeholders"]]
    assert UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID in ids
    assert GENERIC_FREIGHTER_COMBO_ID in ids
    military = next(
        entry
        for entry in payload["placeholders"]
        if entry["id"] == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
    )
    assert military["hullId"] == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
    assert military["count"] == 2
    assert military["buildSlotUsage"] == 1
    assert military["militaryScoreDelta2xMin"] <= military["militaryScoreDelta2xMax"]
    assert [event["type"] for event in events] == ["complete"]
    assert events[0]["placeholders"] == payload["placeholders"]
    assert events[0]["solutionCount"] == 0
    assert events[0]["solutions"] == []


def test_exact_payload_does_not_emit_post_unsat_placeholders(sample_turn):
    from api.analytics.military_score_inference.inference_api_payload import (
        inference_result_to_api_payload,
    )

    catalog = _empty_catalog()
    observation = _observation(warship_delta=1, freighter_delta=1)
    problem = InferenceProblem(observation=observation, aggregate_actions=())
    result = InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={})
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    assert "placeholders" not in payload
    assert payload["solutions"] == []


def test_inference_api_payload_without_turn_keeps_empty_placeholders_when_unspecified():
    payload = inference_api_payload(
        status=STATUS_MODERATE_RESIDUAL,
        summary="Moderate military leftover (11)",
        solutions=(),
        diagnostics={},
        observation=_observation(warship_delta=2, military_delta_2x=22),
    )
    assert payload["placeholders"] == []
    assert payload["unexplainedMilitaryDelta2x"] == 22


def test_persisted_residual_row_round_trips_filled_placeholders_and_leftover():
    from api.serialization.inference_row_persistence import (
        persisted_inference_row_from_json,
        persisted_inference_row_from_wire_complete,
        persisted_inference_row_to_json,
        wire_complete_from_persisted_row,
    )

    placeholders = post_unsat_placeholders(
        _observation(warship_delta=2, freighter_delta=1, military_delta_2x=22),
        **_catalog_parts(),
    )
    row = persisted_inference_row_from_wire_complete(
        {
            "type": "complete",
            "status": STATUS_MODERATE_RESIDUAL,
            "summary": "Moderate military leftover (11)",
            "solutionCount": 0,
            "isComplete": True,
            "solutions": [],
            "placeholders": placeholders,
            "unexplainedMilitaryDelta2x": 22,
        }
    )
    assert row.placeholders == placeholders
    assert row.unexplained_military_delta_2x == 22
    stored = persisted_inference_row_to_json(row)
    assert stored["placeholders"] == placeholders
    assert stored["unexplainedMilitaryDelta2x"] == 22
    loaded = persisted_inference_row_from_json(stored)
    assert loaded.placeholders == placeholders
    wire = wire_complete_from_persisted_row(loaded)
    assert wire["placeholders"] == placeholders
    assert wire["unexplainedMilitaryDelta2x"] == 22
    assert wire["solutionCount"] == 0
    assert wire["solutions"] == []
