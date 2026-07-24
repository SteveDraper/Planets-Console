"""Ingest inferred fleet acquisitions from scoreboard deltas and scores held solutions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from api.analytics.fleet.field_constraints import known_built_turn_value
from api.analytics.fleet.scoreboard_ship_totals import iter_current_turn_scores
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.models.game import TurnInfo
from api.models.player import Score

if TYPE_CHECKING:
    from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
    from api.analytics.fleet.scoreboard_placeholder_targets import ScoreboardPlaceholderTarget

SCOREBOARD_SOURCE = "scoreboard"

FleetShipClass = Literal["warship", "freighter"]


def ingest_turn_inferred_acquisitions(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Create scoreboard placeholders and optionally refine them from held solutions."""
    for ledger in snapshot.players:
        ingest_player_inferred_acquisitions(
            ledger,
            turn,
            game_id=snapshot.game_id,
            perspective=snapshot.perspective,
            inference_materialization=inference_materialization,
        )
    return snapshot


def ingest_player_inferred_acquisitions(
    ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> None:
    """Create scoreboard placeholders and optionally refine them for one player ledger."""
    turn_number = turn.settings.turn
    score = _score_for_player(turn, ledger.player_id)
    if score is not None:
        from api.analytics.fleet.scoreboard_placeholder_targets import (
            scoreboard_placeholder_targets,
            should_seed_homeworld_starting_inventory,
        )

        if should_seed_homeworld_starting_inventory(turn):
            _ensure_homeworld_starting_inventory_rows(
                ledger,
                turn=turn,
                shell_turn=turn_number,
            )
        targets = scoreboard_placeholder_targets(score, turn)
        if targets is not None:
            for target in targets:
                _ensure_placeholder_target_rows(
                    ledger,
                    target=target,
                    shell_turn=turn_number,
                )

    if inference_materialization is not None:
        from api.analytics.fleet.inferred_acquisition_refine import (
            refine_player_inferred_acquisitions_from_scores,
        )

        refine_player_inferred_acquisitions_from_scores(
            ledger,
            turn,
            game_id=game_id,
            perspective=perspective,
            inference_materialization=inference_materialization,
        )


def _score_for_player(turn: TurnInfo, player_id: int) -> Score | None:
    for score in iter_current_turn_scores(turn):
        if score.ownerid == player_id:
            return score
    return None


def _ensure_homeworld_starting_inventory_rows(
    ledger: FleetAcquisitionLedger,
    *,
    turn: TurnInfo,
    shell_turn: int,
) -> None:
    """Seed homeworld starting ships not represented in accelerated scoreboard deltas."""
    from api.analytics.fleet.scoreboard_placeholder_targets import (
        homeworld_starting_inventory_counts,
    )

    freighters, warships = homeworld_starting_inventory_counts(turn)
    _ensure_starting_inventory_rows(
        ledger,
        shell_turn=shell_turn,
        ship_class="freighter",
        expected_count=freighters,
    )
    _ensure_starting_inventory_rows(
        ledger,
        shell_turn=shell_turn,
        ship_class="warship",
        expected_count=warships,
    )


def _ensure_starting_inventory_rows(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    ship_class: FleetShipClass,
    expected_count: int,
) -> None:
    if expected_count <= 0:
        return
    existing = _homeworld_starting_inventory_rows(ledger, shell_turn, ship_class=ship_class)
    for _ in range(expected_count - len(existing)):
        fields, option_sets = _starting_inventory_fields_and_option_sets(ship_class)
        record = FleetShipRecord(
            record_id=str(uuid.uuid4()),
            fields=fields,
            build_option_sets=option_sets,
            display_default_option_set_index=0,
        )
        append_fleet_evidence_event(
            record,
            _homeworld_starting_inventory_event(
                turn=shell_turn,
                ship_class=ship_class,
            ),
        )
        ledger.records.append(record)


def _homeworld_starting_inventory_rows(
    ledger: FleetAcquisitionLedger,
    shell_turn: int,
    *,
    ship_class: FleetShipClass,
) -> list[FleetShipRecord]:
    rows: list[FleetShipRecord] = []
    for record in ledger.records:
        if record.disposition != "active":
            continue
        for event in record.events:
            if event.kind != "scoreboard_delta" or event.turn != shell_turn:
                continue
            if not event.payload.get("homeworldStartingInventory"):
                continue
            if event.payload.get("shipClass") == ship_class:
                rows.append(record)
                break
    return rows


def _starting_inventory_fields_and_option_sets(
    ship_class: FleetShipClass,
) -> tuple[FleetShipRecordFields, list[FleetBuildOptionSet]]:
    """Field constraints and option sets for homeworld starting inventory rows.

    Freighters are known MDSF + Transwarp (Nu starter fit) so observation match
    can use a standard lock-compatible option set rather than an empty pool.
    """
    if ship_class == "freighter":
        from api.analytics.fleet.scoreboard_placeholder_targets import (
            homeworld_starting_freighter_engine_id,
            homeworld_starting_freighter_hull_id,
        )

        hull_id = homeworld_starting_freighter_hull_id()
        engine_id = homeworld_starting_freighter_engine_id()
        return (
            FleetShipRecordFields(
                built_turn=FleetFieldKnown(1),
                hull=FleetFieldKnown(hull_id),
                engine=FleetFieldKnown(engine_id),
            ),
            [
                FleetBuildOptionSet(
                    hull_id=hull_id,
                    engine_id=engine_id,
                    beam_count=0,
                    launcher_count=0,
                )
            ],
        )
    return (
        FleetShipRecordFields(built_turn=FleetFieldKnown(1)),
        [],
    )


def _homeworld_starting_inventory_event(
    *,
    turn: int,
    ship_class: FleetShipClass,
) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="scoreboard_delta",
        turn=turn,
        source=SCOREBOARD_SOURCE,
        payload={
            "shipClass": ship_class,
            "warshipDelta": 0,
            "freighterDelta": 0,
            "homeworldStartingInventory": True,
        },
    )


def _ensure_placeholder_target_rows(
    ledger: FleetAcquisitionLedger,
    *,
    target: ScoreboardPlaceholderTarget,
    shell_turn: int,
) -> None:
    _ensure_placeholder_rows(
        ledger,
        shell_turn=shell_turn,
        built_turn=target.host_turn,
        ship_class="warship",
        expected_count=max(0, target.warship_delta),
        warship_delta=target.warship_delta,
        freighter_delta=0,
    )
    _ensure_placeholder_rows(
        ledger,
        shell_turn=shell_turn,
        built_turn=target.host_turn,
        ship_class="freighter",
        expected_count=max(0, target.freighter_delta),
        warship_delta=0,
        freighter_delta=target.freighter_delta,
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
                segment_host_turn=built_turn if built_turn < shell_turn else None,
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
        if known_built_turn_value(record) == built_turn
    ]


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
    segment_host_turn: int | None = None,
) -> FleetEvidenceEvent:
    payload: dict[str, object] = {
        "shipClass": ship_class,
        "warshipDelta": warship_delta,
        "freighterDelta": freighter_delta,
    }
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
