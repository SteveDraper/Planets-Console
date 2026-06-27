"""Ingest inferred fleet acquisitions from scoreboard deltas and scores held solutions."""

from __future__ import annotations

import uuid
from typing import Literal

from api.analytics.fleet.held_solutions import (
    FleetAcceleratedSegment,
    FleetHeldInference,
    FleetInferenceMaterialization,
)
from api.analytics.fleet.scoreboard_counts import iter_current_turn_scores
from api.analytics.fleet.serialization import (
    append_fleet_evidence_event,
    fleet_build_option_set_from_inference_ship_build,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
    accelerated_inference_segments,
    is_first_reliable_scoreboard_turn,
)
from api.analytics.military_score_inference.inference_api_payload import (
    inference_solution_ship_build_from_wire,
    inference_wire_ship_build_entries,
    inference_wire_solution_objective_value,
)
from api.analytics.military_score_inference.models import InferenceSolutionShipBuild
from api.analytics.military_score_inference.ship_build_combos import (
    is_generic_zero_military_score_combo_id,
)
from api.analytics.scores.export_wire import ranked_solutions_from_wire
from api.models.game import TurnInfo

SCOREBOARD_SOURCE = "scoreboard"
INFERENCE_SOURCE = "scores.inference"

FleetShipClass = Literal["warship", "freighter"]


def ingest_turn_inferred_acquisitions(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Create scoreboard placeholders and optionally refine them from held solutions."""
    snapshot = _create_scoreboard_placeholders(snapshot, turn)
    if inference_materialization is not None:
        snapshot = _refine_inferred_acquisitions_from_scores(
            snapshot,
            turn,
            inference_materialization=inference_materialization,
        )
    return snapshot


def _create_scoreboard_placeholders(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
) -> FleetTurnSnapshot:
    """Create inferred placeholder rows for positive scoreboard warship/freighter deltas."""
    turn_number = turn.settings.turn
    ledgers_by_player_id = {ledger.player_id: ledger for ledger in snapshot.players}
    accelerated_first_reliable = is_first_reliable_scoreboard_turn(turn_number, turn.settings)

    for score in iter_current_turn_scores(turn):
        ledger = ledgers_by_player_id.get(score.ownerid)
        if ledger is None:
            continue
        if accelerated_first_reliable:
            _create_accelerated_scoreboard_placeholders(
                ledger,
                score=score,
                turn=turn,
                shell_turn=turn_number,
            )
            continue

        warship_builds = max(0, score.shipchange)
        freighter_builds = max(0, score.freighterchange)
        _ensure_placeholder_rows(
            ledger,
            shell_turn=turn_number,
            built_turn=turn_number,
            ship_class="warship",
            expected_count=warship_builds,
            warship_delta=warship_builds,
            freighter_delta=0,
        )
        _ensure_placeholder_rows(
            ledger,
            shell_turn=turn_number,
            built_turn=turn_number,
            ship_class="freighter",
            expected_count=freighter_builds,
            warship_delta=0,
            freighter_delta=freighter_builds,
        )

    return snapshot


def _create_accelerated_scoreboard_placeholders(
    ledger: FleetAcquisitionLedger,
    *,
    score,
    turn: TurnInfo,
    shell_turn: int,
) -> None:
    """Create placeholders from accelerated segment ship counts on first reliable turn N."""
    segments = accelerated_inference_segments(score, turn)
    if segments is None:
        return
    for segment in segments:
        _ensure_accelerated_segment_placeholders(
            ledger,
            segment=segment,
            shell_turn=shell_turn,
        )


def _ensure_accelerated_segment_placeholders(
    ledger: FleetAcquisitionLedger,
    *,
    segment: AcceleratedInferenceSegment,
    shell_turn: int,
) -> None:
    _ensure_placeholder_rows(
        ledger,
        shell_turn=shell_turn,
        built_turn=segment.host_turn,
        ship_class="warship",
        expected_count=max(0, segment.warship_delta),
        warship_delta=segment.warship_delta,
        freighter_delta=0,
        segment_id=segment.segment_id,
    )
    _ensure_placeholder_rows(
        ledger,
        shell_turn=shell_turn,
        built_turn=segment.host_turn,
        ship_class="freighter",
        expected_count=max(0, segment.freighter_delta),
        warship_delta=0,
        freighter_delta=segment.freighter_delta,
        segment_id=segment.segment_id,
    )


def _refine_inferred_acquisitions_from_scores(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization,
) -> FleetTurnSnapshot:
    """Attach fleet build option sets from top-K held solutions to placeholder rows."""
    turn_number = turn.settings.turn
    inference = inference_materialization.inference
    load_turn = inference_materialization.load_turn
    accelerated_first_reliable = is_first_reliable_scoreboard_turn(turn_number, turn.settings)
    for ledger in snapshot.players:
        if not _ledger_has_placeholders_for_turn(ledger, turn_number):
            continue
        held = inference.held_inference_for_player(
            game_id=snapshot.game_id,
            perspective=snapshot.perspective,
            host_turn=turn_number,
            player_id=ledger.player_id,
            turn=turn,
            load_turn=load_turn,
        )
        if accelerated_first_reliable and held.accelerated_segments:
            _refine_accelerated_player_placeholders(
                ledger,
                shell_turn=turn_number,
                held=held,
            )
            continue
        if not held.solutions:
            continue
        _refine_player_placeholders(
            ledger,
            shell_turn=turn_number,
            solutions=list(held.solutions),
            search_status=held.search_status,
        )

    return snapshot


def _refine_accelerated_player_placeholders(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    held: FleetHeldInference,
) -> None:
    for segment in held.accelerated_segments:
        if not segment.solutions:
            continue
        search_status = segment.search_status or held.search_status
        warship_placeholders = _placeholder_rows_for_built_turn(
            ledger,
            shell_turn=shell_turn,
            built_turn=segment.host_turn,
            ship_class="warship",
        )
        freighter_placeholders = _placeholder_rows_for_built_turn(
            ledger,
            shell_turn=shell_turn,
            built_turn=segment.host_turn,
            ship_class="freighter",
        )
        _assign_option_sets_to_placeholders(
            warship_placeholders,
            _expanded_builds_by_solution(list(segment.solutions), ship_class="warship"),
            shell_turn=shell_turn,
            search_status=search_status,
            segment=segment,
        )
        _assign_option_sets_to_placeholders(
            freighter_placeholders,
            _expanded_builds_by_solution(list(segment.solutions), ship_class="freighter"),
            shell_turn=shell_turn,
            search_status=search_status,
            segment=segment,
        )


def _ensure_placeholder_rows(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    built_turn: int,
    ship_class: FleetShipClass,
    expected_count: int,
    warship_delta: int,
    freighter_delta: int,
    segment_id: str | None = None,
) -> None:
    if expected_count <= 0:
        return
    existing = _placeholder_rows_for_built_turn(
        ledger,
        shell_turn=shell_turn,
        built_turn=built_turn,
        ship_class=ship_class,
    )
    for _ in range(expected_count - len(existing)):
        record = FleetShipRecord(
            record_id=str(uuid.uuid4()),
            fields=FleetShipRecordFields(
                built_turn=FleetFieldKnown(built_turn),
            ),
        )
        append_fleet_evidence_event(
            record,
            _scoreboard_delta_event(
                turn=shell_turn,
                ship_class=ship_class,
                warship_delta=warship_delta,
                freighter_delta=freighter_delta,
                segment_id=segment_id,
                segment_host_turn=built_turn if segment_id is not None else None,
            ),
        )
        ledger.records.append(record)


def _ledger_has_placeholders_for_turn(
    ledger: FleetAcquisitionLedger,
    turn_number: int,
) -> bool:
    return bool(
        _placeholder_rows_for_turn(ledger, turn_number, ship_class="warship")
        or _placeholder_rows_for_turn(ledger, turn_number, ship_class="freighter")
    )


def _placeholder_rows_for_turn(
    ledger: FleetAcquisitionLedger,
    turn_number: int,
    *,
    ship_class: FleetShipClass,
) -> list[FleetShipRecord]:
    rows: list[FleetShipRecord] = []
    for record in ledger.records:
        if record.disposition != "active":
            continue
        event = _scoreboard_acquisition_event(record, turn_number)
        if event is None:
            continue
        if event.payload.get("shipClass") == ship_class:
            rows.append(record)
    return rows


def _placeholder_rows_for_built_turn(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    built_turn: int,
    ship_class: FleetShipClass,
) -> list[FleetShipRecord]:
    return [
        record
        for record in _placeholder_rows_for_turn(ledger, shell_turn, ship_class=ship_class)
        if _known_built_turn(record) == built_turn
    ]


def _known_built_turn(record: FleetShipRecord) -> int | None:
    built_turn = record.fields.built_turn
    if isinstance(built_turn, FleetFieldKnown) and isinstance(built_turn.value, int):
        return built_turn.value
    return None


def _scoreboard_acquisition_event(
    record: FleetShipRecord,
    turn_number: int,
) -> FleetEvidenceEvent | None:
    for event in record.events:
        if event.kind != "scoreboard_delta" or event.turn != turn_number:
            continue
        warship_delta = event.payload.get("warshipDelta", 0)
        freighter_delta = event.payload.get("freighterDelta", 0)
        if not isinstance(warship_delta, int) or isinstance(warship_delta, bool):
            continue
        if not isinstance(freighter_delta, int) or isinstance(freighter_delta, bool):
            continue
        if warship_delta > 0 or freighter_delta > 0:
            return event
    return None


def _scoreboard_delta_event(
    *,
    turn: int,
    ship_class: FleetShipClass,
    warship_delta: int,
    freighter_delta: int,
    segment_id: str | None = None,
    segment_host_turn: int | None = None,
) -> FleetEvidenceEvent:
    payload: dict[str, object] = {
        "shipClass": ship_class,
        "warshipDelta": warship_delta,
        "freighterDelta": freighter_delta,
    }
    if segment_id is not None:
        payload["segmentId"] = segment_id
    if segment_host_turn is not None:
        payload["segmentHostTurn"] = segment_host_turn
        payload["acceleratedIngest"] = True
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="scoreboard_delta",
        turn=turn,
        source=SCOREBOARD_SOURCE,
        payload=payload,
    )


def _refine_player_placeholders(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    solutions: list[dict[str, object]],
    search_status: str,
) -> None:
    ranked = ranked_solutions_from_wire(solutions)
    warship_placeholders = _placeholder_rows_for_turn(
        ledger,
        shell_turn,
        ship_class="warship",
    )
    freighter_placeholders = _placeholder_rows_for_turn(
        ledger,
        shell_turn,
        ship_class="freighter",
    )
    _assign_option_sets_to_placeholders(
        warship_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="warship"),
        shell_turn=shell_turn,
        search_status=search_status,
    )
    _assign_option_sets_to_placeholders(
        freighter_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="freighter"),
        shell_turn=shell_turn,
        search_status=search_status,
    )


def _expanded_builds_by_solution(
    solutions: list[dict[str, object]],
    *,
    ship_class: FleetShipClass,
) -> list[list[FleetBuildOptionSet]]:
    per_solution: list[list[FleetBuildOptionSet]] = []
    for solution in solutions:
        rank_weight = inference_wire_solution_objective_value(solution)
        expanded: list[FleetBuildOptionSet] = []
        for wire_build in inference_wire_ship_build_entries(solution):
            ship_build = inference_solution_ship_build_from_wire(wire_build)
            if ship_build is None:
                continue
            if _inference_ship_build_class(ship_build) != ship_class:
                continue
            option_set = fleet_build_option_set_from_inference_ship_build(
                ship_build,
                solution_rank_weight=rank_weight,
            )
            expanded.extend([option_set] * ship_build.count)
        per_solution.append(expanded)
    return per_solution


def _assign_option_sets_to_placeholders(
    placeholders: list[FleetShipRecord],
    builds_by_solution: list[list[FleetBuildOptionSet]],
    *,
    shell_turn: int,
    search_status: str,
    segment: FleetAcceleratedSegment | None = None,
) -> None:
    for index, record in enumerate(placeholders):
        option_sets = _option_sets_for_slot(builds_by_solution, index)
        if not option_sets:
            continue
        prior_sets = tuple(record.build_option_sets)
        if prior_sets == option_sets:
            continue
        record.build_option_sets = list(option_sets)
        record.display_default_option_set_index = _default_option_set_index(option_sets)
        _ensure_unknown_spec_fields(record)
        append_fleet_evidence_event(
            record,
            _inference_update_event(
                turn=shell_turn,
                search_status=search_status,
                option_set_count=len(option_sets),
                segment=segment,
            ),
        )


def _option_sets_for_slot(
    builds_by_solution: list[list[FleetBuildOptionSet]],
    slot_index: int,
) -> tuple[FleetBuildOptionSet, ...]:
    best_by_combo_key: dict[str, FleetBuildOptionSet] = {}
    for solution_builds in builds_by_solution:
        if slot_index >= len(solution_builds):
            continue
        option_set = solution_builds[slot_index]
        combo_key = option_set.combo_id or option_set.label
        existing = best_by_combo_key.get(combo_key)
        if existing is None or option_set.solution_rank_weight > existing.solution_rank_weight:
            best_by_combo_key[combo_key] = option_set
    ordered = sorted(
        best_by_combo_key.values(),
        key=lambda option_set: option_set.solution_rank_weight,
        reverse=True,
    )
    return tuple(ordered)


def _default_option_set_index(option_sets: tuple[FleetBuildOptionSet, ...]) -> int:
    best_index = 0
    best_weight = option_sets[0].solution_rank_weight
    for index, option_set in enumerate(option_sets[1:], start=1):
        if option_set.solution_rank_weight > best_weight:
            best_weight = option_set.solution_rank_weight
            best_index = index
    return best_index


def _ensure_unknown_spec_fields(record: FleetShipRecord) -> None:
    if not isinstance(record.fields.ship_id, FleetFieldKnown):
        record.fields.ship_id = FleetFieldUnknown()
    if not isinstance(record.fields.hull, FleetFieldKnown):
        record.fields.hull = FleetFieldUnknown()
    if not isinstance(record.fields.engine, FleetFieldKnown):
        record.fields.engine = FleetFieldUnknown()
    if not isinstance(record.fields.beams, FleetFieldKnown):
        record.fields.beams = FleetFieldUnknown()
    if not isinstance(record.fields.launchers, FleetFieldKnown):
        record.fields.launchers = FleetFieldUnknown()
    if not isinstance(record.fields.location, FleetFieldKnown):
        record.fields.location = FleetFieldUnknown()


def _inference_ship_build_class(ship_build: InferenceSolutionShipBuild) -> FleetShipClass:
    if is_generic_zero_military_score_combo_id(ship_build.combo_id):
        return "freighter"
    return "warship"


def _inference_update_event(
    *,
    turn: int,
    search_status: str,
    option_set_count: int,
    segment: FleetAcceleratedSegment | None = None,
) -> FleetEvidenceEvent:
    payload: dict[str, object] = {
        "searchStatus": search_status,
        "optionSetCount": option_set_count,
    }
    if segment is not None:
        payload["segmentId"] = segment.segment_id
        payload["segmentHostTurn"] = segment.host_turn
        payload["acceleratedIngest"] = True
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="inference_update",
        turn=turn,
        source=INFERENCE_SOURCE,
        payload=payload,
    )
