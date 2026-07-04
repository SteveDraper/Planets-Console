"""Shared helpers for player-scoped fleet gap-fill tests."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_services import FleetComputeServices, turn_chain_through
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.scores_exports_helpers import GAME_ID, first_player_id, perspective, put_persisted_row
from tests.test_fleet_persistence import _put_provenance_final_snapshot

__all__ = [
    "ensure_fleet_export_gap_fill_context",
    "install_mid_chain_put_ledger_gate",
    "materialize_chain_from_coordinator_module",
    "require_turns",
    "roster_ids",
    "seed_provenance_snapshot",
    "two_players_from_turn",
]


def roster_ids(turn: TurnInfo) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def require_turns(
    load_turn: Callable[[int], TurnInfo | None],
    *turn_numbers: int,
) -> tuple[TurnInfo, ...]:
    turns = tuple(load_turn(turn_number) for turn_number in turn_numbers)
    missing = [
        turn_number
        for turn_number, turn in zip(turn_numbers, turns, strict=True)
        if turn is None
    ]
    assert not missing, f"missing turns: {missing}"
    return turns


def two_players_from_turn(turn: TurnInfo) -> tuple[int, int]:
    roster = roster_ids(turn)
    assert len(roster) > 1
    return roster[0], roster[1]


def seed_provenance_snapshot(
    persistence: FleetSnapshotPersistenceService,
    load_turn: Callable[[int], TurnInfo | None],
    *,
    from_turn: int = 109,
) -> TurnInfo:
    turn, = require_turns(load_turn, from_turn)
    _put_provenance_final_snapshot(persistence, GAME_ID, 1, turn)
    return turn


def ensure_fleet_export_gap_fill_context(
    sample_turn,
    memory_backend,
    *,
    turn_number: int = 8,
):
    """Export-ensure context with per-player prerequisites through T-1 (one-turn gap at T)."""
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
    from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger

    player_id = first_player_id(sample_turn)
    other_player_id = sample_turn.scores[1].ownerid
    host_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
    )
    stored_turns = turn_chain_through(host_turn)
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    persp = perspective(sample_turn)
    final_provenance = FleetMaterializationProvenance(
        turn_evidence_at_n=True,
        prior_ledger_at_n_minus_1=True,
    )

    for prior_turn in range(1, turn_number):
        prior_turn_info = stored_turns[prior_turn]
        put_persisted_row(
            inference_persistence,
            prior_turn_info,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seed",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )
        fleet_persistence.put_ledger(
            GAME_ID,
            persp,
            prior_turn,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(
                    GAME_ID,
                    persp,
                    prior_turn_info,
                    player_id,
                ),
                provenance=final_provenance,
            ),
        )

    put_persisted_row(
        inference_persistence,
        host_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )

    ctx = export_chain_query_context(
        host_turn,
        persistence=inference_persistence,
        stored_turns=stored_turns,
    )
    fleet_services = ctx.export_services["fleet"]
    ctx.export_services["fleet"] = FleetComputeServices(
        persistence=fleet_persistence,
        game_id=GAME_ID,
        perspective=persp,
        load_turn=stored_turns.get,
        inference_materialization=fleet_services.inference_materialization,
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=persp,
        turn=turn_number,
        player_id=player_id,
    )
    return ctx, scope, player_id, other_player_id, fleet_persistence


def materialize_chain_from_coordinator_module():
    return __import__(
        "api.analytics.fleet.gap_fill_coordinator",
        fromlist=["_materialize_fleet_ledger_chain_for_player"],
    )._materialize_fleet_ledger_chain_for_player


def install_mid_chain_put_ledger_gate(
    persistence: FleetSnapshotPersistenceService,
    *,
    player_id: int,
    turn_number: int,
    leader_mid_chain: threading.Event,
    release_leader: threading.Event,
) -> None:
    original_put_ledger = persistence.put_ledger
    mid_chain_puts = 0

    def hooked_put_ledger(*args: Any, **kwargs: Any) -> None:
        nonlocal mid_chain_puts
        hooked_turn_number = args[2]
        hooked_player_id = args[3]
        original_put_ledger(*args, **kwargs)
        if (
            hooked_player_id == player_id
            and hooked_turn_number == turn_number
            and mid_chain_puts == 0
        ):
            mid_chain_puts += 1
            leader_mid_chain.set()
            assert release_leader.wait(timeout=5)

    persistence.put_ledger = hooked_put_ledger  # type: ignore[method-assign]
