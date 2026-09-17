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


def test_uncharacterized_roster_persist_does_not_unique_fill_next_turn_sat_catalog(
    sample_turn,
    persistence,
    synthetic_catalog_context,
):
    from api.analytics.military_score_inference.ship_build_combos import ship_build_upper_bound
    from api.analytics.military_score_inference.ship_transfer_families import (
        build_ship_transfer_catalog_fragment,
    )
    from api.concepts.ship_build_military import ship_build_military_score_delta_2x

    from tests.fixtures.ship_transfer_families import _transfer_catalog_kwargs

    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    result = military_sat_refusal_from_turn(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        (_singleton_unknown_hull_warship(),),
    )
    assert result is not None
    wire = _persist_refusal(persistence, result, player_id=3)
    assert wire["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert wire["status"] != "exact"
    assert wire["solutions"] == []
    assert all(
        "hullId" not in entry
        for entry in wire["placeholders"]
        if entry.get("id") == PLACEHOLDER_DEPARTURE_ID
    )

    unique_fill = _singleton_unknown_hull_warship()
    military_2x = ship_build_military_score_delta_2x(
        synthetic_catalog_context["hulls_by_id"][24],
        synthetic_catalog_context["engines_by_id"][1],
        synthetic_catalog_context["beams_by_id"][1],
        None,
        beam_count=2,
        launcher_count=0,
    )
    next_observation = _observation(
        warship_delta=0, freighter_delta=0, military_delta_2x=military_2x
    )
    fragment = build_ship_transfer_catalog_fragment(
        next_observation,
        peer_rows=(),
        prior_fleet_records=(unique_fill,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
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
    assert pins[0]["kind"] == "exact_set"
    assert pins[0]["shipClass"] == "warship"
    records = {entry["recordId"]: entry for entry in pins[0]["records"]}
    assert records["r-traded"]["disposition"] == "traded"
    assert records["r-traded"]["counterpartyPlayerId"] == 5
    assert records["r-lost"]["disposition"] == "lost"
    assert "counterpartyPlayerId" not in records["r-lost"]


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
    assert pins == []


def test_exact_set_from_turn_names_known_spec_record_ids(
    sample_turn,
    synthetic_catalog_context,
):
    from api.analytics.military_score_inference.departure_pin_persist import (
        persistable_departure_pins_from_turn,
    )

    from tests.fixtures.ship_transfer_families import _known_warship_record

    record, _ = _known_warship_record(synthetic_catalog_context)
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    turn = replace(
        without_player_minefields(sample_turn, observation.player_id),
        scores=(),
        ships=(),
    )
    pins = persistable_departure_pins_from_turn(observation, turn, (record,))
    assert len(pins) == 1
    assert pins[0]["kind"] == "exact_set"
    assert pins[0]["records"][0]["recordId"] == record.record_id
    assert pins[0]["records"][0]["disposition"] == "lost"


def test_exact_persist_round_trips_departure_pins(persistence):
    from api.analytics.military_score_inference.solver import STATUS_EXACT

    pins = [
        {
            "kind": "exact_set",
            "shipClass": "warship",
            "records": [
                {"recordId": "r1", "disposition": "lost"},
                {
                    "recordId": "r2",
                    "disposition": "traded",
                    "counterpartyPlayerId": 5,
                },
            ],
        }
    ]
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
    assert replayed["departurePins"] == pins


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
