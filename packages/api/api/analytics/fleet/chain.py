"""Materialize fleet turn snapshots by chaining from prior turns."""

from __future__ import annotations

import copy
from collections.abc import Callable

from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.analytics.turn_roster import iter_turn_players
from api.errors import NotFoundError
from api.models.game import TurnInfo


def ensure_fleet_baseline(
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    baseline_turn_number: int | None = None,
) -> FleetTurnSnapshot:
    """Return an empty per-player fleet ledger for turn 1 (fleet ensure baseline)."""
    snapshot_turn = (
        baseline_turn_number if baseline_turn_number is not None else turn.settings.turn
    )
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


def apply_fleet_turn_delta(snapshot: FleetTurnSnapshot, turn: TurnInfo) -> FleetTurnSnapshot:
    """Apply evidence from shell turn T only.

    Direct observation ingest (#118) and scores integration (#119+) extend this hook.
    """
    _ = turn
    return snapshot


def get_or_materialize_fleet_snapshot(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
) -> FleetTurnSnapshot:
    """Return a cached snapshot or materialize turn T from T-1 plus turn-T delta."""
    turn_number = turn.settings.turn
    cached = persistence.get_snapshot(game_id, perspective, turn_number)
    if cached is not None:
        return cached

    ancestor_turn = 0
    current_snapshot: FleetTurnSnapshot | None = None
    for prior_turn_number in range(turn_number - 1, 0, -1):
        prior_snapshot = persistence.get_snapshot(game_id, perspective, prior_turn_number)
        if prior_snapshot is not None:
            ancestor_turn = prior_turn_number
            current_snapshot = prior_snapshot
            break

    start_turn = ancestor_turn + 1
    implicit_baseline = (
        ancestor_turn == 0 and turn_number > 1 and load_turn(1) is None
    )
    if implicit_baseline and start_turn == 1:
        start_turn = 2

    for materialize_turn in range(start_turn, turn_number + 1):
        prior_turn_rst_missing = (
            materialize_turn > 1 and load_turn(materialize_turn - 1) is None
        )
        if prior_turn_rst_missing and not (
            implicit_baseline and materialize_turn == start_turn
        ):
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {materialize_turn - 1} "
                f"for game {game_id} perspective {perspective}"
            )

        if materialize_turn == turn_number:
            turn_info = turn
        else:
            turn_info = load_turn(materialize_turn)

        if materialize_turn == 1:
            snapshot = ensure_fleet_baseline(game_id, perspective, turn_info)
        elif implicit_baseline and current_snapshot is None:
            baseline = ensure_fleet_baseline(
                game_id,
                perspective,
                turn_info,
                baseline_turn_number=1,
            )
            snapshot = advance_snapshot_to_turn(
                baseline,
                turn_info,
                game_id=game_id,
                perspective=perspective,
            )
        else:
            assert current_snapshot is not None
            snapshot = advance_snapshot_to_turn(
                current_snapshot,
                turn_info,
                game_id=game_id,
                perspective=perspective,
            )

        snapshot = apply_fleet_turn_delta(snapshot, turn_info)
        persistence.put_snapshot(game_id, perspective, materialize_turn, snapshot)
        current_snapshot = snapshot

    assert current_snapshot is not None
    return current_snapshot
