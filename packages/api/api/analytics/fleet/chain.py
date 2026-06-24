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


def apply_fleet_turn_delta(snapshot: FleetTurnSnapshot, turn: TurnInfo) -> FleetTurnSnapshot:
    """Apply evidence from shell turn T only.

    Direct observation ingest (#118) and scores integration (#119+) extend this hook.
    """
    _ = turn
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


def _materialize_and_persist_turn(
    persistence: FleetSnapshotPersistenceService,
    *,
    game_id: int,
    perspective: int,
    materialize_turn: int,
    prior_snapshot: FleetTurnSnapshot,
    turn_info: TurnInfo,
) -> FleetTurnSnapshot:
    snapshot = advance_snapshot_to_turn(
        prior_snapshot,
        turn_info,
        game_id=game_id,
        perspective=perspective,
    )
    snapshot = apply_fleet_turn_delta(snapshot, turn_info)
    persistence.put_snapshot(game_id, perspective, materialize_turn, snapshot)
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

    loaded_turns: dict[int, TurnInfo | None] = {}

    def cached_load(stored_turn_number: int) -> TurnInfo | None:
        if stored_turn_number not in loaded_turns:
            loaded_turns[stored_turn_number] = load_turn(stored_turn_number)
        return loaded_turns[stored_turn_number]

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

    def require_prior_rst(materialize_turn: int, *, allow_missing_turn_one_rst: bool) -> None:
        if materialize_turn <= 1:
            return
        prior_turn_number = materialize_turn - 1
        if allow_missing_turn_one_rst and prior_turn_number == 1:
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
    skip_turn_one_rst = anchor_turn == 0 and turn_number > 1 and cached_load(1) is None
    start_turn = anchor_turn + 1

    if skip_turn_one_rst:
        if start_turn == 1:
            start_turn = 2
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
        )
        persistence.put_snapshot(game_id, perspective, 1, turn_one_snapshot)
        current_snapshot = turn_one_snapshot
        if turn_number == 1:
            return turn_one_snapshot
        start_turn = 2

    for materialize_turn in range(start_turn, turn_number + 1):
        require_prior_rst(
            materialize_turn,
            allow_missing_turn_one_rst=skip_turn_one_rst and materialize_turn == start_turn,
        )
        turn_info = require_turn(materialize_turn)
        current_snapshot = _materialize_and_persist_turn(
            persistence,
            game_id=game_id,
            perspective=perspective,
            materialize_turn=materialize_turn,
            prior_snapshot=current_snapshot,
            turn_info=turn_info,
        )

    return current_snapshot
