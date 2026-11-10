"""On-walk persist stamping: walk persists stamp the mark, stray persists bump it."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn
from tests.on_walk_helpers import (
    accept_shell,
    fleet_persistence,
    shell_scope,
    submit_shell,
)
from tests.scores_exports_helpers import first_player_id


def _scores_node(
    orchestrator: ComputeOrchestrator,
    ctx,
    player_id: int,
    host_turn: int,
    *,
    open_turn: int,
    backfill: bool,
) -> None:
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=host_turn,
        player_id=player_id,
    )
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=open_turn, backfill_earlier_turns=backfill),
    )


def _invalidation(ctx, orchestrator: ComputeOrchestrator) -> InferenceInvalidationService:
    return InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=fleet_persistence(ctx),
        orchestrator=lambda: orchestrator,
    )


def test_on_walk_scoreboard_persist_stamps_and_a_stray_persist_bumps(sample_turn):
    """Membership is the producing node's, so a walk persist stamps even after a stray bump."""
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = fleet_persistence(ctx)
    orchestrator = submit_shell(ctx, SCORES_ANALYTIC_ID, 10, player_id)
    invalidation = _invalidation(ctx, orchestrator)

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 1
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 11, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 2
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 1

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 2
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 1


def test_two_open_turns_stamp_without_discarding_each_other(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = fleet_persistence(ctx)
    orchestrator = submit_shell(ctx, SCORES_ANALYTIC_ID, 8, player_id)
    submit_shell(ctx, SCORES_ANALYTIC_ID, 10, player_id, orchestrator=orchestrator)
    opens = {
        turn: orchestrator.submission_open_for(
            shell_scope(ctx, SCORES_ANALYTIC_ID, turn, player_id)
        )
        for turn in (8, 10)
    }
    assert opens[8] == SubmissionOpen(open_turn=8, backfill_earlier_turns=True, on_walk=True)
    assert opens[10] == SubmissionOpen(open_turn=10, backfill_earlier_turns=True, on_walk=True)
    invalidation = _invalidation(ctx, orchestrator)

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)
    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 8, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 1
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0


def test_backfill_scoreboard_persist_that_opened_no_walk_bumps(sample_turn):
    """Backfill on is not membership: the producing node must be on a walk."""
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = fleet_persistence(ctx)
    accept_shell(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    orchestrator = ComputeOrchestrator(compute_registry={})
    _scores_node(orchestrator, ctx, player_id, 10, open_turn=10, backfill=True)

    _invalidation(ctx, orchestrator).on_scores_row_persisted(
        ctx.game_id, ctx.perspective, 10, player_id
    )

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 2
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 1
