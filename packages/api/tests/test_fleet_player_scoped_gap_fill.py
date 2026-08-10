"""Player-scoped fleet gap-fill and export ensure (#179)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import (
    get_or_materialize_fleet_ledger_for_player,
)
from api.analytics.fleet.exports import ensure_fleet_export
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import GAME_ID, export_chain_query_context
from tests.fleet_player_scoped_gap_fill_helpers import (
    ensure_fleet_export_gap_fill_context,
    require_turns,
    roster_ids,
    seed_provenance_snapshot,
    two_players_from_turn,
)
from tests.scores_exports_helpers import first_player_id, put_persisted_row
from tests.test_fleet_persistence import (
    _inference_materialization_for_fleet,
    _seed_scores_rows_for_all_players,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_inference_row_scheduler():
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )

    reset_inference_row_scheduler_for_tests()
    yield
    reset_inference_row_scheduler_for_tests()


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)
        for turn_number in (109, 110, 111, 112):
            turn_data = copy.deepcopy(turn_rst)
            turn_data["settings"]["turn"] = turn_number
            turn_data["game"]["turn"] = turn_number
            backend.put(f"games/628580/1/turns/{turn_number}", turn_data)
    return backend


@pytest.fixture
def persistence(memory_backend):
    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def load_turn(memory_backend):
    def _load(turn_number: int):
        key = f"games/628580/1/turns/{turn_number}"
        try:
            data = memory_backend.get(key)
        except Exception:
            return None
        if data is None:
            return None
        return turn_info_from_json(data)

    return _load


def test_single_player_gap_fill_does_not_materialize_other_players(persistence, load_turn):
    _, turn_112 = require_turns(load_turn, 109, 112)
    player_p, player_q = two_players_from_turn(turn_112)

    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_112,
        load_turn=load_turn,
    )

    for turn_number in range(110, 113):
        assert persistence.has_ledger(628580, 1, turn_number, player_p)
        assert not persistence.has_ledger(628580, 1, turn_number, player_q)


def test_ensure_fleet_export_scoped_to_player_only(sample_turn, memory_backend):
    """Orchestrator fleet ensure for one player must not materialize other roster players."""
    ctx, scope, player_id, other_player_id, fleet_persistence = (
        ensure_fleet_export_gap_fill_context(sample_turn, memory_backend)
    )

    assert ensure_fleet_export(ctx, scope) is True

    assert fleet_persistence.has_final_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
    )
    assert not fleet_persistence.has_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        other_player_id,
    )


def test_nested_ensure_dedupes_same_player_node(sample_turn, memory_backend):
    """Orchestrator fleet ensure is idempotent: second call short-circuits when final.

    ``ensure_fleet_export`` submits via orchestrator; a second ensure of the same
    satisfied scope must not re-submit (is_satisfied short-circuit).
    """
    from api.analytics.export_types import ExportScope
    from api.analytics.fleet.compute_services import turn_chain_through
    from api.compute import export_ensure as export_ensure_module

    player_id = first_player_id(sample_turn)
    turn_number = 8
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    host_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
    )
    stored_turns = turn_chain_through(host_turn)
    ctx = export_chain_query_context(
        host_turn,
        persistence=inference_persistence,
        stored_turns=stored_turns,
        seed_fleet_prerequisites_for=player_id,
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

    scope = ExportScope(
        game_id=GAME_ID,
        perspective=host_turn.player.id,
        turn=turn_number,
        player_id=player_id,
    )
    orchestrator_calls: list[tuple[int, int | None]] = []

    def tracking_ensure(query_ctx, analytic_id, export_scope, **_kwargs):
        orchestrator_calls.append((export_scope.turn, export_scope.player_id))
        # Simulate durable final satisfaction without running the full DAG in-unit.
        from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
        from api.analytics.fleet.compute_services import resolve_fleet_services
        from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger

        services = resolve_fleet_services(query_ctx)
        turn = query_ctx.load_turn(export_scope.turn)
        assert turn is not None
        assert export_scope.player_id is not None
        services.persistence.put_ledger(
            services.game_id,
            services.perspective,
            export_scope.turn,
            export_scope.player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(
                    services.game_id,
                    services.perspective,
                    turn,
                    export_scope.player_id,
                ),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
        return True

    with patch.object(
        export_ensure_module,
        "ensure_export_scope_via_orchestrator",
        side_effect=tracking_ensure,
    ):
        assert ensure_fleet_export(ctx, scope) is True
        assert ensure_fleet_export(ctx, scope) is True

    assert orchestrator_calls == [(turn_number, player_id)]


def test_ensure_fleet_export_does_not_invoke_full_snapshot_materialize(sample_turn, memory_backend):
    ctx, scope, player_id, _, fleet_persistence = ensure_fleet_export_gap_fill_context(
        sample_turn,
        memory_backend,
    )

    def forbid_snapshot(*_args, **_kwargs):
        raise AssertionError("ensure_fleet_export must not call get_or_materialize_fleet_snapshot")

    with patch(
        "api.analytics.fleet.exports.get_or_materialize_fleet_snapshot",
        side_effect=forbid_snapshot,
    ):
        assert ensure_fleet_export(ctx, scope) is True

    assert fleet_persistence.has_final_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
    )


def test_per_player_cache_hit_does_not_require_roster_complete(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player

    (turn,) = require_turns(load_turn, 111)
    roster = roster_ids(turn)
    player_p = roster[0]
    persistence.put_ledger(
        628580,
        1,
        111,
        player_p,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, turn, player_p),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn,
        load_turn=load_turn,
    )

    assert not persistence.has_ledger(628580, 1, 111, roster[1])


def test_per_player_prior_turn_materializes_while_other_scores_inference_in_progress(
    persistence,
    load_turn,
    memory_backend,
):
    """Incident regression (game 628580 turn 8): fleet 409 while scores stream active.

    Per-player materialization of fleet@(T-1) for one player must succeed without
    requiring all-roster snapshot finality when other players' scores@T inference is
    still in progress. Would raise ConflictError under perspective-batch coordinator
    behavior that waited for full-roster ensure-final before one-player access.
    """
    turn_110, turn_111, turn_112 = require_turns(load_turn, 110, 111, 112)
    player_p, player_q = two_players_from_turn(turn_112)

    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    # Terminal scores@111 closes turn evidence so fleet@111 is final and may
    # invalidate scores@112. scores@112 for Q stays incomplete (incident shape).
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)

    inference_persistence.put_row(
        628580,
        1,
        112,
        player_p,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="done-for-p",
            solution_count=1,
            is_complete=True,
            solutions=[],
        ),
    )
    inference_persistence.put_row(
        628580,
        1,
        112,
        player_q,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="still-running",
            solution_count=0,
            is_complete=False,
            solutions=[],
        ),
    )

    assert persistence.get_snapshot(628580, 1, 111) is None
    assert not persistence.has_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert persistence.has_final_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)
    snapshot_111 = persistence.get_snapshot(628580, 1, 111)
    assert snapshot_111 is None or player_q not in {
        ledger.player_id for ledger in snapshot_111.players
    }
    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None


def test_per_player_gap_fill_emits_deferred_scores_invalidation_for_player(
    persistence,
    load_turn,
    memory_backend,
):
    turn_110, turn_111, turn_112 = require_turns(load_turn, 110, 111, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    # Terminal scores@111 required for final fleet@111 -> scores@112 invalidation.
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert persistence.has_final_ledger(628580, 1, 111, player_p)
    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None


def test_per_player_gap_start_independent(persistence, load_turn):
    turn_109, turn_110, turn_111 = require_turns(load_turn, 109, 110, 111)
    player_p, player_q = two_players_from_turn(turn_111)

    seed_provenance_snapshot(persistence, load_turn, from_turn=109)
    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
    )

    assert persistence.has_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)


def test_compute_fleet_fan_out_materializes_all_players_explicitly(persistence, load_turn):
    from api.analytics.compute_context import invoke_analytic_compute
    from api.analytics.fleet import compute_fleet
    from api.analytics.fleet.compute_services import FleetComputeServices

    turn_109, turn_112 = require_turns(load_turn, 109, 112)
    roster_size = len(roster_ids(turn_112))
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    fleet_services = FleetComputeServices(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        inference_materialization=None,
    )

    ledger_calls = 0
    original = get_or_materialize_fleet_ledger_for_player

    def counting_ledger(*args, **kwargs):
        nonlocal ledger_calls
        ledger_calls += 1
        return original(*args, **kwargs)

    with patch(
        "api.analytics.fleet.chain.get_or_materialize_fleet_ledger_for_player",
        side_effect=counting_ledger,
    ):
        invoke_analytic_compute(
            compute_fleet,
            turn_112,
            export_services={"fleet": fleet_services},
        )

    assert ledger_calls == roster_size
