"""Refine inferred acquisition placeholders from scores held solutions."""

from __future__ import annotations

import uuid

from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.fleet.scoreboard_ingest import (
    FleetShipClass,
    _placeholder_rows_for_turn,
)
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetTurnSnapshot,
)
from api.analytics.scores.export_wire import ranked_solutions_from_wire
from api.models.game import TurnInfo

INFERENCE_SOURCE = "scores.inference"


def refine_inferred_acquisitions_from_scores(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    inference: FleetInferenceSupport | None,
    load_turn,
) -> FleetTurnSnapshot:
    """Attach fleet build option sets from top-K held solutions to placeholder rows."""
    if inference is None:
        return snapshot

    turn_number = turn.settings.turn
    for ledger in snapshot.players:
        held = inference.held_inference_for_player(
            game_id=game_id,
            perspective=perspective,
            host_turn=turn_number,
            player_id=ledger.player_id,
            turn=turn,
            load_turn=load_turn,
        )
        if not held.solutions:
            continue
        _refine_player_placeholders(
            ledger,
            turn_number=turn_number,
            solutions=list(held.solutions),
            search_status=held.search_status,
        )

    return snapshot


def _refine_player_placeholders(
    ledger,
    *,
    turn_number: int,
    solutions: list[dict[str, object]],
    search_status: str,
) -> None:
    ranked = ranked_solutions_from_wire(solutions)
    warship_placeholders = _placeholder_rows_for_turn(
        ledger,
        turn_number,
        ship_class="warship",
    )
    freighter_placeholders = _placeholder_rows_for_turn(
        ledger,
        turn_number,
        ship_class="freighter",
    )
    _assign_option_sets_to_placeholders(
        warship_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="warship"),
        turn_number=turn_number,
        search_status=search_status,
    )
    _assign_option_sets_to_placeholders(
        freighter_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="freighter"),
        turn_number=turn_number,
        search_status=search_status,
    )


def _expanded_builds_by_solution(
    solutions: list[dict[str, object]],
    *,
    ship_class: FleetShipClass,
) -> list[list[FleetBuildOptionSet]]:
    per_solution: list[list[FleetBuildOptionSet]] = []
    for solution in solutions:
        rank_weight = _solution_rank_weight(solution)
        expanded: list[FleetBuildOptionSet] = []
        for wire_build in _wire_ship_builds(solution):
            if _wire_ship_build_class(wire_build) != ship_class:
                continue
            count = wire_build.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                continue
            option_set = _option_set_from_wire_build(wire_build, rank_weight)
            expanded.extend([option_set] * count)
        per_solution.append(expanded)
    return per_solution


def _assign_option_sets_to_placeholders(
    placeholders: list[FleetShipRecord],
    builds_by_solution: list[list[FleetBuildOptionSet]],
    *,
    turn_number: int,
    search_status: str,
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
        record.fields.built_turn = FleetFieldKnown(turn_number)
        _ensure_unknown_spec_fields(record)
        append_fleet_evidence_event(
            record,
            _inference_update_event(
                turn=turn_number,
                search_status=search_status,
                option_set_count=len(option_sets),
            ),
        )


def _option_sets_for_slot(
    builds_by_solution: list[list[FleetBuildOptionSet]],
    slot_index: int,
) -> tuple[FleetBuildOptionSet, ...]:
    seen_combo_ids: set[str] = set()
    ordered: list[FleetBuildOptionSet] = []
    for solution_builds in builds_by_solution:
        if slot_index >= len(solution_builds):
            continue
        option_set = solution_builds[slot_index]
        combo_key = option_set.combo_id or option_set.label
        if combo_key in seen_combo_ids:
            continue
        seen_combo_ids.add(combo_key)
        ordered.append(option_set)
    ordered.sort(key=lambda option_set: option_set.solution_rank_weight, reverse=True)
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


def _wire_ship_builds(solution: dict[str, object]) -> list[dict[str, object]]:
    raw = solution.get("shipBuilds")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _solution_rank_weight(solution: dict[str, object]) -> int:
    objective = solution.get("objectiveValue", 0)
    if isinstance(objective, bool) or not isinstance(objective, (int, float)):
        return 0
    return int(objective)


def _option_set_from_wire_build(
    wire_build: dict[str, object],
    solution_rank_weight: int,
) -> FleetBuildOptionSet:
    return FleetBuildOptionSet(
        combo_id=_optional_str(wire_build.get("comboId")),
        label=str(wire_build.get("label", "")),
        solution_rank_weight=solution_rank_weight,
        hull_id=_optional_int(wire_build.get("hullId")),
        engine_id=_optional_int(wire_build.get("engineId")),
        beam_id=_optional_int(wire_build.get("beamId")),
        torp_id=_optional_int(wire_build.get("torpId")),
        beam_count=_int_field(wire_build.get("beamCount")),
        launcher_count=_int_field(wire_build.get("launcherCount")),
    )


def _wire_ship_build_class(wire_build: dict[str, object]) -> FleetShipClass:
    combo_id = str(wire_build.get("comboId", ""))
    if "freighter" in combo_id.lower():
        return "freighter"
    return "warship"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _int_field(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _inference_update_event(
    *,
    turn: int,
    search_status: str,
    option_set_count: int,
) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="inference_update",
        turn=turn,
        source=INFERENCE_SOURCE,
        payload={
            "searchStatus": search_status,
            "optionSetCount": option_set_count,
        },
    )
