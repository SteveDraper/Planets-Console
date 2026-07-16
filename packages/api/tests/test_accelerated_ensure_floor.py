"""Regression: accelerated-start ensure floor (game 680224 shape).

Mid-accelerated games often store the first reliable scoreboard turn N and later
turns while omitting unreliable turns 1..N-1 for a perspective (or leaving a
hole such as turn 1 present and turn 2 missing). Scores/fleet ensure must not
walk into those turns, and fleet gap-fill must start at N.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import ExportScope
from api.analytics.fleet.chain import (
    _first_stored_rst_turn,
    get_or_materialize_fleet_ledger_for_player,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    resolve_prior_turn_fleet_torp_overlay,
)
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.scores_exports_helpers import first_player_id

REPO_ROOT = Path(__file__).resolve().parents[3]
GAME_680224_TURNS = REPO_ROOT / ".data" / "games" / "680224" / "2" / "turns"


def _turn_at(sample_turn, turn_number: int, *, acceleratedturns: int = 3):
    return replace(
        sample_turn,
        settings=replace(
            sample_turn.settings,
            turn=turn_number,
            acceleratedturns=acceleratedturns,
        ),
        game=replace(sample_turn.game, turn=turn_number),
    )


def _680224_shaped_store(sample_turn) -> dict[int, object]:
    """Stored turns shaped like mid-accel game 680224: {1, 3, 4}, hole at 2."""
    return {
        1: _turn_at(sample_turn, 1),
        3: _turn_at(sample_turn, 3),
        4: _turn_at(sample_turn, 4),
    }


def test_accelerated_ensure_floor(sample_turn):
    normal = replace(sample_turn.settings, acceleratedturns=0)
    assert accelerated_ensure_floor(normal, 5) == 1
    assert accelerated_ensure_floor(normal, 1) == 1
    # Call-site patterns: turn == floor (baseline), dep < floor
    assert 1 == accelerated_ensure_floor(normal, 1)
    assert 0 < accelerated_ensure_floor(normal, 5)
    assert not (1 < accelerated_ensure_floor(normal, 5))

    accel = replace(sample_turn.settings, acceleratedturns=3)
    assert accelerated_ensure_floor(accel, 2) == 1
    assert accelerated_ensure_floor(accel, 3) == 3
    assert accelerated_ensure_floor(accel, 4) == 3
    assert accelerated_ensure_floor(accel, 1) == 1
    assert 1 == accelerated_ensure_floor(accel, 1)
    assert 3 == accelerated_ensure_floor(accel, 3)
    assert 4 != accelerated_ensure_floor(accel, 4)
    assert 2 < accelerated_ensure_floor(accel, 4)
    assert not (2 < accelerated_ensure_floor(accel, 2))
    assert not (3 < accelerated_ensure_floor(accel, 4))


def test_scores_ensure_walk_skips_missing_turn_below_accelerated_floor(sample_turn):
    """scores@4 must not fail with turn_not_stored when turn 2 is absent (680224)."""
    stored = _680224_shaped_store(sample_turn)
    turn4 = stored[4]
    player_id = first_player_id(sample_turn)
    ctx = export_chain_query_context(turn4, stored_turns=stored)
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=4,
        player_id=player_id,
    )

    walk = walk_dependency_tree(ctx, "scores", scope, visiting=set(), force_root=True)

    assert walk.turn_unavailable is None
    pending_turns = {(analytic_id, scope.turn) for analytic_id, scope, _ in walk.pending_ensure}
    assert ("scores", 4) in pending_turns
    assert ("fleet", 3) in pending_turns
    assert ("scores", 3) in pending_turns
    assert ("fleet", 2) not in pending_turns
    assert ("fleet", 1) not in pending_turns


def test_scores_ensure_walk_at_first_reliable_turn_skips_prior_fleet(sample_turn):
    stored = _680224_shaped_store(sample_turn)
    turn3 = stored[3]
    player_id = first_player_id(sample_turn)
    ctx = export_chain_query_context(turn3, stored_turns=stored)
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=3,
        player_id=player_id,
    )

    walk = walk_dependency_tree(ctx, "scores", scope, visiting=set(), force_root=True)

    assert walk.turn_unavailable is None
    pending_turns = {(analytic_id, scope.turn) for analytic_id, scope, _ in walk.pending_ensure}
    assert ("scores", 3) in pending_turns
    assert ("fleet", 2) not in pending_turns


def test_fleet_chain_starts_at_accelerated_floor_with_turn_two_hole(sample_turn):
    stored = _680224_shaped_store(sample_turn)
    turn4 = stored[4]
    player_id = first_player_id(sample_turn)

    def load_turn(turn_number: int):
        return stored.get(turn_number)

    assert _first_stored_rst_turn(load_turn, 4) == 1
    assert _first_stored_rst_turn(load_turn, 4, min_turn=3) == 3

    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    persisted = get_or_materialize_fleet_ledger_for_player(
        persistence,
        turn4.game.id,
        turn4.player.id,
        player_id,
        turn4,
        load_turn=load_turn,
        inference_materialization=None,
        query_context=None,
    )

    assert persisted.ledger.player_id == player_id
    assert persistence.get_ledger(turn4.game.id, turn4.player.id, 4, player_id) is not None
    assert persistence.get_ledger(turn4.game.id, turn4.player.id, 3, player_id) is not None
    assert persistence.get_ledger(turn4.game.id, turn4.player.id, 2, player_id) is None
    assert persistence.get_ledger(turn4.game.id, turn4.player.id, 1, player_id) is None

    floor_ledger = persistence.get_ledger(turn4.game.id, turn4.player.id, 3, player_id)
    assert floor_ledger is not None
    assert floor_ledger.provenance.prior_ledger_at_n_minus_1 is True


def test_prior_fleet_torp_overlay_not_applicable_at_first_reliable_turn(sample_turn):
    turn3 = _turn_at(sample_turn, 3)
    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=turn3,
        player_id=first_player_id(sample_turn),
        load_turn=lambda n: turn3 if n == 3 else None,
        export_services=None,
        ensure=False,
    )
    assert resolution.input_status == "not_applicable"
    assert resolution.overlay is None


@pytest.mark.skipif(
    not GAME_680224_TURNS.joinpath("4.json").is_file(),
    reason="local .data/games/680224 only",
)
def test_680224_local_store_missing_turn_two():
    """Sanity-check the real local corpus still matches the regression shape."""
    stored = sorted(int(path.stem) for path in GAME_680224_TURNS.glob("*.json"))
    assert 2 not in stored
    assert 3 in stored
    assert 4 in stored
