"""Persist, stream, and export of uncharacterized roster (#489)."""

from __future__ import annotations

import json
from dataclasses import replace

from api.analytics.military_score_inference.military_sat_admission import (
    military_sat_refusal_from_turn,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
)
from api.serialization.inference_row_persistence import persisted_inference_row_to_json
from api.serialization.uncharacterized_roster import PLACEHOLDER_DEPARTURE_ID
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.transport.inference_stream import stream_inference_ndjson
from api.transport.inference_stream_wire import (
    domain_event_to_wire_events,
    row_complete_to_complete_wire_event,
)

from tests.fixtures.military_score_inference import _observation, without_player_minefields
from tests.fixtures.pp_gap_transfer import birds_row
from tests.fixtures.ship_transfer_families import _singleton_unknown_hull_warship
from tests.scores_exports_helpers import GAME_ID, inference_target_player_id, scores_query_context


def _observation_from_row(row) -> InferenceObservation:
    return InferenceObservation(
        player_id=row.player_id,
        turn=15,
        military_delta_2x=row.military_delta_2x,
        warship_delta=row.warship_delta,
        freighter_delta=row.freighter_delta,
        priority_point_delta=row.priority_point_delta,
        starbases_owned=row.starbases,
        is_after_ship_limit=False,
        planet_delta=row.planet_delta,
        starbase_delta=row.starbase_delta,
    )


def _persist_refusal(
    persistence: InferenceRowPersistenceService,
    result,
    *,
    player_id: int,
    host_turn: int = 111,
) -> dict[str, object]:
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(result),
        game_id=GAME_ID,
        perspective=8,
        host_turn=host_turn,
        player_id=player_id,
    )
    stored = persistence.get_row(GAME_ID, 8, host_turn, player_id)
    assert stored is not None
    wire = persistence.wire_complete_for_row(GAME_ID, 8, host_turn, player_id)
    assert wire is not None
    return wire


def test_persist_round_trips_uncharacterized_roster_bound_leftover_departure_and_signatures(
    sample_turn,
    persistence,
):
    warship_observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    warship_result = military_sat_refusal_from_turn(
        warship_observation,
        without_player_minefields(sample_turn, warship_observation.player_id),
        (_singleton_unknown_hull_warship(),),
    )
    assert warship_result is not None
    warship_wire = _persist_refusal(persistence, warship_result, player_id=3)

    assert warship_wire["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert warship_wire["status"] != "exact"
    assert warship_wire["solutions"] == []
    assert warship_wire["solutionCount"] == 0
    leftover = warship_wire["leftover"]
    assert leftover["kind"] == "unknown_loss_bound"
    assert "unexplainedMilitaryDelta2x" not in leftover
    assert "unexplainedMilitaryDelta2x" not in warship_wire
    stored = persistence.get_row(GAME_ID, 8, 111, 3)
    assert stored is not None
    stored_json = persisted_inference_row_to_json(stored)
    assert "unexplainedMilitaryDelta2x" not in stored_json
    assert stored_json["leftover"]["kind"] == "unknown_loss_bound"
    departures = [
        entry
        for entry in warship_wire["placeholders"]
        if entry.get("id") == PLACEHOLDER_DEPARTURE_ID
    ]
    assert departures
    assert all(entry["shipClass"] in {"warship", "freighter"} for entry in departures)
    assert any(entry["shipClass"] == "warship" for entry in departures)
    assert all("hullId" not in entry for entry in departures)

    idle_observation = _observation_from_row(birds_row())
    idle_result = military_sat_refusal_from_turn(
        idle_observation,
        without_player_minefields(sample_turn, idle_observation.player_id),
    )
    assert idle_result is not None
    idle_wire = _persist_refusal(persistence, idle_result, player_id=4)
    assert idle_wire["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert idle_wire["solutions"] == []
    signatures = idle_wire["latticeSignatures"]
    assert len(signatures) == 2
    assert {entry["shipClass"] for entry in signatures} == {"warship", "freighter"}
    assert all("objectiveValue" not in entry for entry in signatures)
    idle_stored = persistence.get_row(GAME_ID, 8, 111, 4)
    assert idle_stored is not None
    assert persisted_inference_row_to_json(idle_stored)["latticeSignatures"] == signatures


def test_stream_complete_carries_roster_payload_without_solution_events(sample_turn):
    observation = _observation_from_row(birds_row())
    result = military_sat_refusal_from_turn(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
    )
    assert result is not None
    complete = row_complete_with_summary(result)
    live_events = domain_event_to_wire_events(
        complete,
        observation=observation,
        turn=sample_turn,
    )
    assert [event["type"] for event in live_events] == ["complete"]
    live = live_events[0]
    assert live["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert live["solutionCount"] == 0
    assert live["solutions"] == []
    assert live["leftover"]["kind"] == "unknown_loss_bound"
    assert "unexplainedMilitaryDelta2x" not in live
    assert len(live["latticeSignatures"]) == 2

    persist_replay = row_complete_to_complete_wire_event(complete)
    streamed = [
        json.loads(line) for line in stream_inference_ndjson(lambda: iter([persist_replay]))
    ]
    assert [event["type"] for event in streamed] == ["complete"]
    assert streamed[0]["latticeSignatures"] == live["latticeSignatures"]
    assert streamed[0]["leftover"] == live["leftover"]


def test_uncharacterized_roster_does_not_start_mine_residual_sticky_prior(persistence):
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(
                status=STATUS_UNCHARACTERIZED_ROSTER,
                solutions=(),
                diagnostics={},
            ),
            summary=STATUS_UNCHARACTERIZED_ROSTER,
        ),
        game_id=GAME_ID,
        perspective=8,
        host_turn=110,
        player_id=3,
    )
    assert persistence.has_mine_residual_sticky_prior(GAME_ID, 8, 111, 3) is False


def test_export_exposes_roster_status_tagged_leftover_placeholders_and_signatures(
    sample_turn,
    persistence,
):
    observation = _observation_from_row(birds_row())
    result = military_sat_refusal_from_turn(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
    )
    assert result is not None
    player_id = inference_target_player_id(sample_turn)
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(result),
        game_id=GAME_ID,
        perspective=sample_turn.player.id,
        host_turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    queried = scores_query_context(sample_turn, persistence=persistence).query(
        "scores",
        [
            "$.meta.searchStatus",
            "$.status",
            "$.solutions[0]",
            "$.placeholders",
            "$.leftover",
            "$.latticeSignatures",
            "$.unexplainedMilitaryDelta2x",
        ],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert queried.status == "ok"
    assert queried.paths["$.meta.searchStatus"].value == "complete"
    assert queried.paths["$.status"].value == STATUS_UNCHARACTERIZED_ROSTER
    assert queried.paths["$.solutions[0]"].kind == "none"
    assert queried.paths["$.leftover"].value["kind"] == "unknown_loss_bound"
    assert "unexplainedMilitaryDelta2x" not in queried.paths["$.leftover"].value
    assert queried.paths["$.unexplainedMilitaryDelta2x"].kind == "none"
    signatures = queried.paths["$.latticeSignatures"].value
    assert len(signatures) == 2
    assert {entry["shipClass"] for entry in signatures} == {"warship", "freighter"}
    assert queried.paths["$.placeholders"].kind != "none"
    assert all(
        "hullId" not in entry
        for entry in queried.paths["$.placeholders"].value
        if entry.get("id") == PLACEHOLDER_DEPARTURE_ID
    )


def test_uncharacterized_roster_persist_does_not_unique_fill_next_turn_sat_catalog(
    sample_turn,
    persistence,
    synthetic_catalog_context,
):
    from api.analytics.fleet.chain import ensure_fleet_baseline
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
    from api.analytics.military_score_inference.ship_build_combos import ship_build_upper_bound
    from api.analytics.military_score_inference.ship_transfer_families import (
        build_ship_transfer_catalog_fragment,
    )
    from api.analytics.scores.export_services import ScoresExportContext

    from tests.fixtures.ship_transfer_families import _transfer_catalog_kwargs
    from tests.fleet_fixtures import ledger_for_player

    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    sat_turn = without_player_minefields(sample_turn, observation.player_id)
    result = military_sat_refusal_from_turn(observation, sat_turn)
    assert result is not None
    player_id = observation.player_id
    host_turn = sat_turn.settings.turn
    perspective = 8
    wire = _persist_refusal(persistence, result, player_id=player_id, host_turn=host_turn)
    stored = persistence.get_row(GAME_ID, perspective, host_turn, player_id)
    assert stored is not None
    assert stored.status == STATUS_UNCHARACTERIZED_ROSTER
    assert stored.status != "exact"
    assert stored.solutions == []
    assert wire["status"] == stored.status
    assert wire["solutions"] == stored.solutions
    assert stored.leftover is not None
    assert stored.leftover["kind"] == "unknown_loss_bound"
    assert stored.placeholders is not None
    assert all(
        "hullId" not in entry
        for entry in stored.placeholders
        if entry.get("id") == PLACEHOLDER_DEPARTURE_ID
    )

    ingest_turn = replace(
        sat_turn,
        ships=(),
        scores=tuple(
            replace(
                score,
                shipchange=observation.warship_delta,
                freighterchange=observation.freighter_delta,
            )
            if score.ownerid == player_id
            else score
            for score in sat_turn.scores
        ),
    )
    inference = FleetInferenceSupport(
        scores_services=ScoresExportContext(persistence=persistence),
    )
    held = inference.held_inference_for_scoreboard_turn(
        game_id=GAME_ID,
        perspective=perspective,
        scoreboard_turn=host_turn,
        player_id=player_id,
        turn=ingest_turn,
        load_turn=lambda _turn_number: ingest_turn,
    )
    assert held.solutions == ()
    assert all(
        "hullId" not in entry
        for entry in held.placeholders
        if entry.get("id") == PLACEHOLDER_DEPARTURE_ID
    )
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(GAME_ID, perspective, ingest_turn),
        ingest_turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=inference,
            load_turn=lambda _turn_number: ingest_turn,
        ),
    )
    prior_fleet_records = tuple(ledger_for_player(snapshot, player_id).records)
    assert all(not record.build_option_sets for record in prior_fleet_records)

    next_observation = _observation(warship_delta=0, freighter_delta=0, military_delta_2x=0)
    fragment = build_ship_transfer_catalog_fragment(
        next_observation,
        peer_rows=(),
        prior_fleet_records=prior_fleet_records,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert fragment.prior_warship_departure_cap == 0
    assert fragment.extra_warship_capacity == 0
    assert (
        ship_build_upper_bound(
            next_observation,
            is_warship=True,
            is_freighter=False,
            extra_warship_capacity=fragment.extra_warship_capacity,
        )
        == 0
    )


def test_exact_set_pin_persist_names_record_ids_lost_and_traded():
    from api.analytics.military_score_inference.count_lattice import DeparturePin
    from api.analytics.military_score_inference.departure_pin_persist import (
        persistable_departure_pins,
    )
    from api.analytics.military_score_inference.public_scoreboard_pairing import (
        PairingMatch,
        PublicScoreboardPairing,
    )

    pairing = PublicScoreboardPairing(
        matches=(
            PairingMatch(
                family="gift",
                counterparty_player_id=5,
                warship_delta=-1,
                freighter_delta=0,
                counterparty_military_delta_2x=40,
                transfer_count=1,
                pinned_class="warship",
            ),
        ),
        unmatched_warship_drop=1,
        unmatched_freighter_drop=0,
    )
    pins = persistable_departure_pins(
        (
            DeparturePin(
                kind="exact_set",
                ship_class="warship",
                record_ids=("r-traded", "r-lost"),
            ),
        ),
        pairing,
    )
    assert len(pins) == 1
    assert pins[0].kind == "exact_set"
    assert pins[0].ship_class == "warship"
    records = {entry.record_id: entry for entry in pins[0].records}
    assert records["r-traded"].disposition == "traded"
    assert records["r-traded"].counterparty_player_id == 5
    assert records["r-lost"].disposition == "lost"
    assert records["r-lost"].counterparty_player_id is None


def test_spec_only_pin_persist_omits_record_id_retirement_list():
    from api.analytics.military_score_inference.count_lattice import DeparturePin
    from api.analytics.military_score_inference.departure_pin_persist import (
        persistable_departure_pins,
    )
    from api.analytics.military_score_inference.public_scoreboard_pairing import (
        PublicScoreboardPairing,
    )

    pins = persistable_departure_pins(
        (DeparturePin(kind="spec_only", ship_class="warship"),),
        PublicScoreboardPairing(
            matches=(),
            unmatched_warship_drop=1,
            unmatched_freighter_drop=0,
        ),
    )
    assert pins == ()


def test_exact_set_from_turn_names_known_spec_record_ids(
    sample_turn,
    synthetic_catalog_context,
):
    from api.analytics.military_score_inference.departure_pin_persist import (
        persistable_departure_pins,
    )
    from api.analytics.military_score_inference.military_sat_admission import (
        military_sat_admission_from_turn,
    )

    from tests.fixtures.ship_transfer_families import _known_warship_record

    record, _ = _known_warship_record(synthetic_catalog_context)
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    turn = replace(
        without_player_minefields(sample_turn, observation.player_id),
        scores=(),
        ships=(),
    )
    admission, pairing, _idle_dock = military_sat_admission_from_turn(observation, turn, (record,))
    assert admission.admitted is True
    pins = persistable_departure_pins(admission.pins, pairing)
    assert len(pins) == 1
    assert pins[0].kind == "exact_set"
    assert pins[0].records[0].record_id == record.record_id
    assert pins[0].records[0].disposition == "lost"


def test_exact_persist_round_trips_departure_pins(persistence):
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.military_score_inference.uncharacterized_roster_types import (
        ExactSetDeparturePin,
        ExactSetPinRecord,
    )
    from api.serialization.uncharacterized_roster import departure_pins_to_json

    pins = (
        ExactSetDeparturePin(
            ship_class="warship",
            records=(
                ExactSetPinRecord(record_id="r1", disposition="lost"),
                ExactSetPinRecord(
                    record_id="r2",
                    disposition="traded",
                    counterparty_player_id=5,
                ),
            ),
        ),
    )
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(),
                diagnostics={},
                departure_pins=pins,
            ),
            summary="exact",
        ),
        game_id=GAME_ID,
        perspective=8,
        host_turn=111,
        player_id=3,
    )
    replayed = persistence.wire_complete_for_row(GAME_ID, 8, 111, 3)
    assert replayed is not None
    assert replayed["status"] == STATUS_EXACT
    assert replayed["departurePins"] == departure_pins_to_json(pins)


def test_spec_only_exact_persist_omits_departure_pins(persistence):
    from api.analytics.military_score_inference.solver import STATUS_EXACT

    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="exact",
        ),
        game_id=GAME_ID,
        perspective=8,
        host_turn=111,
        player_id=3,
    )
    replayed = persistence.wire_complete_for_row(GAME_ID, 8, 111, 3)
    assert replayed is not None
    assert "departurePins" not in replayed


def test_exact_finalize_persists_admission_pins_without_readmitting(
    sample_turn,
    synthetic_catalog_context,
    persistence,
    monkeypatch,
):
    from api.analytics.military_score_inference.actions import ActionCatalog
    from api.analytics.military_score_inference.departure_pin_persist import (
        persistable_departure_pins,
    )
    from api.analytics.military_score_inference.policy_ladder import (
        finalize_policy_ladder_result,
    )
    from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
    from api.analytics.military_score_inference.policy_ladder_tier_step import (
        run_policy_ladder_tier_step,
    )
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
    from api.serialization.uncharacterized_roster import departure_pins_to_json

    from tests.fixtures.ship_transfer_families import _known_warship_record

    def _solve(problem, **kwargs):
        return InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={})

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.leftover_0_solutions",
        lambda solutions, *_args, **_kwargs: list(solutions),
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        lambda *_args, **_kwargs: ActionCatalog((), (), {}),
    )
    record, _ = _known_warship_record(synthetic_catalog_context)
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    turn = replace(
        without_player_minefields(sample_turn, observation.player_id),
        scores=(),
        ships=(),
    )
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(None)[:1]),
        prior_fleet_records=(record,),
    )
    run_policy_ladder_tier_step(state, observation, turn, time_limit_seconds=1.0)
    assert state.sat_admission is not None
    assert state.sat_admission.admitted is True
    assert state.scoreboard_pairing is not None
    expected = persistable_departure_pins(state.sat_admission.pins, state.scoreboard_pairing)
    assert expected

    def _must_not_readmit(*_args, **_kwargs):
        raise AssertionError("exact finalize must not re-run SAT admission")

    monkeypatch.setattr(
        "api.analytics.military_score_inference.military_sat_admission.resolve_military_sat_admission",
        _must_not_readmit,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.military_sat_admission.military_sat_admission_from_turn",
        _must_not_readmit,
    )
    result, *_ = finalize_policy_ladder_result(state, observation, turn)
    assert result.status == STATUS_EXACT
    assert result.departure_pins == expected
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(result, summary="exact"),
        game_id=GAME_ID,
        perspective=8,
        host_turn=111,
        player_id=3,
    )
    replayed = persistence.wire_complete_for_row(GAME_ID, 8, 111, 3)
    assert replayed is not None
    assert replayed["departurePins"] == departure_pins_to_json(expected)
