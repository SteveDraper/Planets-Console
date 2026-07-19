"""Refine inferred fleet acquisition placeholders from held inference solutions."""

from __future__ import annotations

import uuid

from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.inferred_acquisition_ingest import (
    FleetShipClass,
    _known_built_turn,
    _ledger_has_placeholders_for_turn,
    _placeholder_rows_for_built_turn,
    _placeholder_rows_for_turn,
)
from api.analytics.fleet.observation_ingest import (
    observation_established_full_fit,
    record_has_direct_observation,
)
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
    FleetTurnSnapshot,
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

INFERENCE_SOURCE = "scores.inference"


def refine_inferred_acquisitions_from_scores(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization,
) -> FleetTurnSnapshot:
    """Attach fleet build option sets from top-K held solutions to placeholder rows."""
    for ledger in snapshot.players:
        refine_player_inferred_acquisitions_from_scores(
            ledger,
            turn,
            game_id=snapshot.game_id,
            perspective=snapshot.perspective,
            inference_materialization=inference_materialization,
        )
    return snapshot


def refine_player_inferred_acquisitions_from_scores(
    ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    inference_materialization: FleetInferenceMaterialization,
) -> None:
    """Attach fleet build option sets from top-K held solutions for one player ledger."""
    turn_number = turn.settings.turn
    if not _ledger_has_placeholders_for_turn(ledger, turn_number):
        return
    inference = inference_materialization.inference
    load_turn = inference_materialization.load_turn
    for built_turn in _distinct_placeholder_built_turns(ledger, turn_number):
        held = inference.held_inference_for_placeholder(
            game_id=game_id,
            perspective=perspective,
            shell_turn=turn_number,
            built_turn=built_turn,
            player_id=ledger.player_id,
            turn=turn,
            load_turn=load_turn,
        )
        if not held.solutions:
            continue
        _refine_player_placeholders_for_built_turn(
            ledger,
            shell_turn=turn_number,
            built_turn=built_turn,
            solutions=list(held.solutions),
            search_status=held.search_status,
        )


def _distinct_placeholder_built_turns(
    ledger: FleetAcquisitionLedger,
    shell_turn: int,
) -> tuple[int, ...]:
    built_turns: set[int] = set()
    for ship_class in ("warship", "freighter"):
        for record in _placeholder_rows_for_turn(ledger, shell_turn, ship_class=ship_class):
            built_turn = _known_built_turn(record)
            if built_turn is not None:
                built_turns.add(built_turn)
    return tuple(sorted(built_turns))


def _refine_player_placeholders_for_built_turn(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    built_turn: int,
    solutions: list[dict[str, object]],
    search_status: str,
) -> None:
    ranked = ranked_solutions_from_wire(solutions)
    warship_placeholders = _placeholder_rows_for_built_turn(
        ledger,
        shell_turn=shell_turn,
        built_turn=built_turn,
        ship_class="warship",
    )
    freighter_placeholders = _placeholder_rows_for_built_turn(
        ledger,
        shell_turn=shell_turn,
        built_turn=built_turn,
        ship_class="freighter",
    )
    _assign_option_sets_to_placeholders(
        warship_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="warship"),
        shell_turn=shell_turn,
        search_status=search_status,
        built_turn=built_turn,
    )
    _assign_option_sets_to_placeholders(
        freighter_placeholders,
        _expanded_builds_by_solution(ranked, ship_class="freighter"),
        shell_turn=shell_turn,
        search_status=search_status,
        built_turn=built_turn,
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
    built_turn: int | None = None,
) -> None:
    for index, record in enumerate(placeholders):
        # Full-information observation already locked a confirmed fit; do not
        # replace it with inferred alternates (phase-2 refine after sighting).
        if observation_established_full_fit(record):
            continue
        option_sets = _option_sets_for_slot(builds_by_solution, index)
        if not option_sets:
            continue
        if record_has_direct_observation(record):
            option_sets = _option_sets_respecting_observation_locks(record, option_sets)
            # Foreign-hull (or otherwise incompatible) inference candidates were
            # all dropped. Keep observation's prior sets (often a hull-only seed)
            # rather than wiping to [].
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
                built_turn=built_turn,
            ),
        )


def _option_sets_respecting_observation_locks(
    record: FleetShipRecord,
    option_sets: tuple[FleetBuildOptionSet, ...],
) -> tuple[FleetBuildOptionSet, ...]:
    """Keep only inference option sets compatible with observation-known axes.

    Partial fog sightings lock hull (and any positively observed component ids
    and counts). Option sets that contradict those locks are dropped -- rewriting
    a foreign hull or retaining a 4-beam fit after a 1-beam sighting left illegal
    display rows. Unknown weapon/engine axes on a compatible set stay open for
    display from that set, then receive the locked values via merge.
    """
    from api.analytics.fleet.observation_option_locks import (
        observation_locks_from_record,
        option_sets_respecting_locks,
    )

    return option_sets_respecting_locks(
        option_sets,
        observation_locks_from_record(record),
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
    """Clear component fields so display comes from build option sets.

    Do not touch ``ship_id``: option sets never carry host ids, and scoreboard
    ``lte`` bounds / known sightings must survive refine (including persist
    phase-2 refine after observation ingest already tightened bounds).
    """
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
    built_turn: int | None = None,
) -> FleetEvidenceEvent:
    payload: dict[str, object] = {
        "searchStatus": search_status,
        "optionSetCount": option_set_count,
    }
    if built_turn is not None and built_turn < turn:
        payload["segmentHostTurn"] = built_turn
        payload["acceleratedIngest"] = True
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="inference_update",
        turn=turn,
        source=INFERENCE_SOURCE,
        payload=payload,
    )
