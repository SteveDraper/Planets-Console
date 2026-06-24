"""Materialize fleet turn snapshots by chaining from prior turns."""

from __future__ import annotations

import copy
from collections.abc import Callable

from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.analytics.turn_roster import iter_turn_players
from api.errors import NotFoundError
from api.models.game import TurnInfo


def ensure_fleet_baseline(
    game_id: int,
    perspective: int,
    turn: TurnInfo,
) -> FleetTurnSnapshot:
    """Return an empty per-player fleet ledger for turn 1 (fleet ensure baseline)."""
    return FleetTurnSnapshot(
        analytic_id="fleet",
        game_id=game_id,
        perspective=perspective,
        turn=turn.settings.turn,
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
            players.append(
                FleetAcquisitionLedger(player_id=player.id, player_name=player.username)
            )
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

    if turn_number == 1:
        snapshot = ensure_fleet_baseline(game_id, perspective, turn)
    else:
        prior_turn = load_turn(turn_number - 1)
        if prior_turn is None:
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {turn_number - 1} "
                f"for game {game_id} perspective {perspective}"
            )
        prior_snapshot = get_or_materialize_fleet_snapshot(
            persistence,
            game_id,
            perspective,
            prior_turn,
            load_turn=load_turn,
        )
        snapshot = advance_snapshot_to_turn(
            prior_snapshot,
            turn,
            game_id=game_id,
            perspective=perspective,
        )

    snapshot = apply_fleet_turn_delta(snapshot, turn)
    persistence.put_snapshot(game_id, perspective, turn_number, snapshot)
    return snapshot
