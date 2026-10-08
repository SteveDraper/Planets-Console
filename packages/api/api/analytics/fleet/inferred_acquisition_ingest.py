"""Ingest inferred fleet acquisitions from scoreboard deltas and scores held solutions."""

from __future__ import annotations

import uuid

from api.analytics.fleet.field_constraints import known_built_turn_value
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.scoreboard_placeholder_targets import (
    ScoreboardPlaceholderTarget,
    scoreboard_placeholder_targets,
)
from api.analytics.fleet.scoreboard_ship_totals import iter_current_turn_scores
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetShipClass,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.concepts.accelerated_scoreboard import (
    HOMEBASE_STARTING_FREIGHTER_ENGINE_ID,
    HOMEBASE_STARTING_FREIGHTER_HULL_ID,
    HomeworldSeedCounts,
    homeworld_seed_counts,
)
from api.models.game import TurnInfo
from api.models.player import Score

SCOREBOARD_SOURCE = "scoreboard"


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
        seed = homeworld_seed_counts(score, turn)
        if seed is not None:
            _ensure_homeworld_starting_inventory_rows(
                ledger,
                shell_turn=turn_number,
                seed=seed,
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
    shell_turn: int,
    seed: HomeworldSeedCounts,
) -> None:
    """Seed homeworld starting ships the build deltas on this shell turn omit."""
    _ensure_starting_inventory_rows(
        ledger,
        shell_turn=shell_turn,
        ship_class="freighter",
        expected_count=seed.freighters,
        count_starter_sighting=seed.sighting_fills_starting_freighter,
    )
    _ensure_starting_inventory_rows(
        ledger,
        shell_turn=shell_turn,
        ship_class="warship",
        expected_count=seed.warships,
        count_starter_sighting=seed.sighting_fills_starting_freighter,
    )


def _ensure_starting_inventory_rows(
    ledger: FleetAcquisitionLedger,
    *,
    shell_turn: int,
    ship_class: FleetShipClass,
    expected_count: int,
    count_starter_sighting: bool,
) -> None:
    if expected_count <= 0:
        return
    existing_count = sum(
        1
        for record in ledger.records
        if _fills_starting_inventory_slot(
            record,
            shell_turn=shell_turn,
            ship_class=ship_class,
            count_starter_sighting=count_starter_sighting,
        )
    )
    for _ in range(expected_count - existing_count):
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


def _fills_starting_inventory_slot(
    record: FleetShipRecord,
    *,
    shell_turn: int,
    ship_class: FleetShipClass,
    count_starter_sighting: bool,
) -> bool:
    """Active row that already accounts for one homeworld starting ship of this class.

    A seed tagged on this shell turn counts. When ``count_starter_sighting`` is
    set, an active built-turn-1 starting-freighter hull also fills the freighter
    slot. ``HomeworldSeedCounts`` sets that flag on the opening reveal only.
    """
    if record.disposition != "active":
        return False
    for event in record.events:
        if event.kind != "scoreboard_delta" or event.turn != shell_turn:
            continue
        if not event.payload.get("homeworldStartingInventory"):
            continue
        if event.payload.get("shipClass") == ship_class:
            return True
    return (
        count_starter_sighting
        and ship_class == "freighter"
        and known_built_turn_value(record) == 1
        and record.fields.hull == FleetFieldKnown(HOMEBASE_STARTING_FREIGHTER_HULL_ID)
    )


def _starting_inventory_fields_and_option_sets(
    ship_class: FleetShipClass,
) -> tuple[FleetShipRecordFields, list[FleetBuildOptionSet]]:
    """Field constraints and option sets for homeworld starting inventory rows.

    Freighters are known MDSF + Transwarp (Nu starter fit) so observation match
    can use a standard lock-compatible option set rather than an empty pool.
    """
    if ship_class == "freighter":
        hull_id = HOMEBASE_STARTING_FREIGHTER_HULL_ID
        engine_id = HOMEBASE_STARTING_FREIGHTER_ENGINE_ID
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
