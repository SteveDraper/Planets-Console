"""Materialize fleet turn snapshots by chaining from prior turns."""

from __future__ import annotations

import copy
from collections.abc import Callable

from api.analytics.fleet.constants import ANALYTIC_ID, GAP_FILL_MAX_RETRIES
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.observation_ingest import ingest_turn_ship_observations
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.analytics.turn_roster import iter_turn_players
from api.errors import ConflictError, NotFoundError
from api.models.game import TurnInfo


class _FleetSnapshotInvalidated(Exception):
    """Gap-fill observed a concurrent fleet snapshot invalidation."""


def ensure_fleet_baseline(
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    baseline_turn_number: int | None = None,
) -> FleetTurnSnapshot:
    """Return an empty per-player fleet ledger for turn 1 (fleet ensure baseline)."""
    snapshot_turn = baseline_turn_number if baseline_turn_number is not None else turn.settings.turn
    return FleetTurnSnapshot(
        analytic_id=ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=snapshot_turn,
        players=[
            FleetAcquisitionLedger(player_id=player.id, player_name=player.username)
            for player in iter_turn_players(turn)
        ],
    )


def advance_snapshot_to_turn(
    prior: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
) -> FleetTurnSnapshot:
    """Copy turn T-1 ledger state forward to shell turn T."""
    ledgers_by_player_id = {ledger.player_id: ledger for ledger in prior.players}
    players: list[FleetAcquisitionLedger] = []
    for player in iter_turn_players(turn):
        prior_ledger = ledgers_by_player_id.get(player.id)
        if prior_ledger is None:
            players.append(FleetAcquisitionLedger(player_id=player.id, player_name=player.username))
            continue
        ledger = copy.deepcopy(prior_ledger)
        ledger.player_name = player.username
        players.append(ledger)
    return FleetTurnSnapshot(
        analytic_id=prior.analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn.settings.turn,
        players=players,
    )


def apply_fleet_turn_delta(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Apply all turn-T fleet evidence deltas for materialization."""
    snapshot = ingest_turn_inferred_acquisitions(
        snapshot,
        turn,
        inference_materialization=inference_materialization,
    )
    snapshot = ingest_turn_ship_observations(snapshot, turn)
    return snapshot


def _find_chain_anchor(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn_number: int,
) -> tuple[int, FleetTurnSnapshot | None]:
    for prior_turn_number in range(turn_number - 1, 0, -1):
        prior_snapshot = persistence.get_snapshot(game_id, perspective, prior_turn_number)
        if prior_snapshot is not None:
            return prior_turn_number, prior_snapshot
    return 0, None


def _first_stored_rst_turn(
    load_turn: Callable[[int], TurnInfo | None],
    turn_number: int,
) -> int | None:
    """Return the lowest stored RST turn in ``1..turn_number``, if any."""
    for stored_turn_number in range(1, turn_number + 1):
        if load_turn(stored_turn_number) is not None:
            return stored_turn_number
    return None


def _assert_invalidation_generation_unchanged(
    persistence: FleetSnapshotPersistenceService,
    *,
    game_id: int,
    perspective: int,
    generation: int,
) -> None:
    if persistence.invalidation_generation(game_id, perspective) != generation:
        raise _FleetSnapshotInvalidated()


def _materialize_and_persist_turn(
    persistence: FleetSnapshotPersistenceService,
    *,
    materialize_turn: int,
    prior_snapshot: FleetTurnSnapshot,
    turn_info: TurnInfo,
    inference_materialization: FleetInferenceMaterialization | None = None,
    invalidation_generation: int,
) -> FleetTurnSnapshot:
    snapshot = advance_snapshot_to_turn(
        prior_snapshot,
        turn_info,
        game_id=prior_snapshot.game_id,
        perspective=prior_snapshot.perspective,
    )
    snapshot = apply_fleet_turn_delta(
        snapshot,
        turn_info,
        inference_materialization=inference_materialization,
    )
    persistence.put_snapshot(
        snapshot.game_id,
        snapshot.perspective,
        materialize_turn,
        snapshot,
    )
    _assert_invalidation_generation_unchanged(
        persistence,
        game_id=snapshot.game_id,
        perspective=snapshot.perspective,
        generation=invalidation_generation,
    )
    return snapshot


def _materialize_fleet_snapshot_chain(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
    invalidation_generation: int,
) -> FleetTurnSnapshot:
    """Gap-fill fleet snapshots from the latest anchor through turn T."""
    turn_number = turn.settings.turn

    loaded_turns: dict[int, TurnInfo | None] = {}

    def cached_load(stored_turn_number: int) -> TurnInfo | None:
        if stored_turn_number not in loaded_turns:
            loaded_turns[stored_turn_number] = load_turn(stored_turn_number)
        return loaded_turns[stored_turn_number]

    resolved_inference_materialization = (
        FleetInferenceMaterialization(
            inference=inference_materialization.inference,
            load_turn=cached_load,
        )
        if inference_materialization is not None
        else None
    )

    def require_turn(materialize_turn: int) -> TurnInfo:
        if materialize_turn == turn_number:
            return turn
        turn_info = cached_load(materialize_turn)
        if turn_info is None:
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {materialize_turn} "
                f"for game {game_id} perspective {perspective}"
            )
        return turn_info

    def require_prior_rst(materialize_turn: int, *, allow_missing_prefix_rst: bool) -> None:
        if materialize_turn <= 1:
            return
        prior_turn_number = materialize_turn - 1
        if allow_missing_prefix_rst:
            return
        if cached_load(prior_turn_number) is None:
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {prior_turn_number} "
                f"for game {game_id} perspective {perspective}"
            )

    anchor_turn, current_snapshot = _find_chain_anchor(
        persistence,
        game_id,
        perspective,
        turn_number,
    )
    first_stored_rst = _first_stored_rst_turn(cached_load, turn_number)
    skip_missing_prefix_rst = (
        anchor_turn == 0
        and turn_number > 1
        and first_stored_rst is not None
        and first_stored_rst > 1
    )
    start_turn = anchor_turn + 1

    if skip_missing_prefix_rst:
        start_turn = first_stored_rst
        first_rst_turn = require_turn(start_turn)
        implicit_baseline = ensure_fleet_baseline(
            game_id,
            perspective,
            first_rst_turn,
            baseline_turn_number=1,
        )
        current_snapshot = advance_snapshot_to_turn(
            implicit_baseline,
            first_rst_turn,
            game_id=game_id,
            perspective=perspective,
        )
    elif anchor_turn == 0:
        turn_one = require_turn(1)
        turn_one_snapshot = apply_fleet_turn_delta(
            ensure_fleet_baseline(game_id, perspective, turn_one),
            turn_one,
            inference_materialization=resolved_inference_materialization,
        )
        persistence.put_snapshot(game_id, perspective, 1, turn_one_snapshot)
        _assert_invalidation_generation_unchanged(
            persistence,
            game_id=game_id,
            perspective=perspective,
            generation=invalidation_generation,
        )
        current_snapshot = turn_one_snapshot
        if turn_number == 1:
            return turn_one_snapshot
        start_turn = 2

    for materialize_turn in range(start_turn, turn_number + 1):
        require_prior_rst(
            materialize_turn,
            allow_missing_prefix_rst=skip_missing_prefix_rst and materialize_turn == start_turn,
        )
        turn_info = require_turn(materialize_turn)
        current_snapshot = _materialize_and_persist_turn(
            persistence,
            materialize_turn=materialize_turn,
            prior_snapshot=current_snapshot,
            turn_info=turn_info,
            inference_materialization=resolved_inference_materialization,
            invalidation_generation=invalidation_generation,
        )

    return current_snapshot


def get_or_materialize_fleet_snapshot(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Return a cached snapshot or materialize turn T from T-1 plus turn-T delta."""
    turn_number = turn.settings.turn
    cached = persistence.get_snapshot(game_id, perspective, turn_number)
    if cached is not None:
        return cached

    for attempt in range(GAP_FILL_MAX_RETRIES):
        invalidation_generation = persistence.invalidation_generation(game_id, perspective)
        try:
            return _materialize_fleet_snapshot_chain(
                persistence,
                game_id,
                perspective,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                invalidation_generation=invalidation_generation,
            )
        except _FleetSnapshotInvalidated:
            if attempt + 1 >= GAP_FILL_MAX_RETRIES:
                break
            continue

    raise ConflictError(
        f"fleet snapshot gap-fill for game {game_id} perspective {perspective} "
        f"turn {turn_number} exceeded {GAP_FILL_MAX_RETRIES} invalidation retries"
    )
