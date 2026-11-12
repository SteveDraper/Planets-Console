"""``begin_scope`` claims a scope without detaching any run.

A scores stream detaches its own rows when it ends. Claiming a scope, whether
the first claim, a scope change or a same-scope preempt, only resets
stream-owned scheduler state: global pause, held submissions and bindings.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    TierLadderRegistration,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.persist_decision import PersistDecision
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run_phase,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeRequest
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.streaming.table_stream.row_run_admission import RowRunPhase

from tests.scores_row_lifecycle_test_helpers import (
    _patch_scores_dag_without_fleet_deps,
    _session_for_player,
)

GAME_ID = 628580
PERSPECTIVE = 1


@pytest.fixture
def scheduler() -> Iterator[InferenceRowScheduler]:
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    yield InferenceRowScheduler()
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()


def _stream_scope(sample_turn, *, turn_offset: int = 0) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn_number=sample_turn.settings.turn + turn_offset,
    )


def _player_session(sample_turn, index: int = 0) -> InferenceRowStreamSession:
    return _session_for_player(sample_turn, player_id=sample_turn.scores[index].ownerid)


def _first_claim(
    scheduler: InferenceRowScheduler, sample_turn, session: InferenceRowStreamSession
) -> None:
    """A background run is registered before any stream claims a scope."""
    assert scheduler.enqueue_tier_ladder(session) is TierLadderRegistration.BACKGROUND
    scheduler.begin_scope(_stream_scope(sample_turn, turn_offset=1))


def _claim_after_a_stream_row(turn_offset: int) -> Callable[..., None]:
    def claim(
        scheduler: InferenceRowScheduler, sample_turn, session: InferenceRowStreamSession
    ) -> None:
        token = scheduler.begin_scope(_stream_scope(sample_turn))
        registration = scheduler.enqueue_tier_ladder(session, stream_token=token)
        assert registration is TierLadderRegistration.STREAM_BOUND
        scheduler.begin_scope(_stream_scope(sample_turn, turn_offset=turn_offset))

    return claim


CLAIMS = {
    "first-claim": _first_claim,
    "scope-change": _claim_after_a_stream_row(turn_offset=1),
    "same-scope-preempt": _claim_after_a_stream_row(turn_offset=0),
}


@pytest.mark.parametrize("claim", CLAIMS.values(), ids=CLAIMS.keys())
def test_begin_scope_detaches_no_run(scheduler, sample_turn, claim):
    session = _player_session(sample_turn)

    claim(scheduler, sample_turn, session)

    assert get_row_run_phase(session.run_id) is RowRunPhase.REGISTERED
    assert session.run_id in scheduler._runs
    assert not session.cancel_token.is_cancelled()
    assert decide_scores_row_persist(session.run_id) == PersistDecision.allow(
        retire_after_write=False
    )


@pytest.mark.parametrize("turn_offset", [1, 0], ids=["scope-change", "same-scope-preempt"])
def test_begin_scope_clears_pause_held_submissions_and_bindings(
    scheduler, sample_turn, turn_offset
):
    scope = _stream_scope(sample_turn)
    token = scheduler.begin_scope(scope)
    bound = _player_session(sample_turn, 0)
    assert (
        scheduler.enqueue_tier_ladder(bound, stream_token=token)
        is TierLadderRegistration.STREAM_BOUND
    )
    scheduler.pause_globally(scope)
    held = _player_session(sample_turn, 1)
    assert scheduler.enqueue_tier_ladder(held, stream_token=token) is TierLadderRegistration.HELD
    assert [submission.stream_token for submission in scheduler._held_initial_submissions] == [
        token
    ]
    assert list(scheduler._stream_bindings) == [token]

    scheduler.begin_scope(_stream_scope(sample_turn, turn_offset=turn_offset))

    assert scheduler._globally_paused is False
    assert scheduler._held_initial_submissions == []
    assert scheduler._stream_bindings == {}
    for session in (bound, held):
        assert get_row_run_phase(session.run_id) is RowRunPhase.REGISTERED


def test_a_walk_node_held_behind_pause_dispatches_after_a_scope_change(
    scheduler, sample_turn, monkeypatch
):
    reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    scope = _stream_scope(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    walk_session = _player_session(sample_turn)
    walk_node_scope = scheduler._root_scope_for_session(walk_session)
    scores_rows = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    walk_ctx = replace(
        walk_session.query_context,
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(scheduler=scheduler, persistence=scores_rows)
        },
    )
    orchestrator = get_compute_orchestrator()
    orchestrator.submit(
        ComputeRequest(scope=walk_node_scope, step_kind=SCORES_TIER_SOLVE, ctx=walk_ctx)
    )
    orchestrator.dispatch_ready_work()
    assert orchestrator.nodes[walk_node_scope].state == "ready"

    scheduler.begin_scope(_stream_scope(sample_turn, turn_offset=1))
    orchestrator.dispatch_ready_work()

    assert orchestrator.nodes[walk_node_scope].state == "running"


def test_stream_resolutions_are_fifo_bounded_across_states(monkeypatch):
    """Soft/hard stream resolutions stay FIFO-bounded (persist phase is separate)."""
    from api.streaming.table_stream import row_stream_resolution_registry as resolutions
    from api.streaming.table_stream.row_stream_resolution import (
        RowStreamResolutionState,
        RowStreamResolutionTrigger,
    )

    monkeypatch.setattr(resolutions, "MAX_STREAM_RESOLUTIONS", 3)
    resolutions.reset_stream_resolution_registry_for_tests()
    try:
        for index in range(5):
            resolutions.transition_stream_resolution(
                f"soft-{index}",
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            )
        for index in range(5):
            resolutions.transition_stream_resolution(
                f"hard-{index}",
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            )
        soft_retained = [
            index
            for index in range(5)
            if (
                (r := resolutions.get_stream_resolution(f"soft-{index}")) is not None
                and r.state is RowStreamResolutionState.SOFT_PROVISIONAL
            )
        ]
        hard_retained = [
            index
            for index in range(5)
            if (
                (r := resolutions.get_stream_resolution(f"hard-{index}")) is not None
                and r.state is RowStreamResolutionState.HARD_TERMINAL
            )
        ]
        assert soft_retained == []
        assert hard_retained == [2, 3, 4]
    finally:
        resolutions.reset_stream_resolution_registry_for_tests()
