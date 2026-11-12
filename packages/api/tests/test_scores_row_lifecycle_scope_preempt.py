"""``begin_scope`` claims a scope without detaching any run.

A scores stream detaches its own rows when it ends. Claiming a scope, whether
the first claim, a scope change or a same-scope preempt, only resets
stream-owned scheduler state: global pause, held submissions and bindings.
Clearing pause releases held work: each held submission is submitted and the
nodes the pause gate held are dispatched.
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
from api.analytics.military_score_inference.inference_stream_scope import (
    InferenceStreamScope,
    scores_root_scope_for_session,
)
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
def test_begin_scope_clears_pause_and_bindings_and_releases_held_submissions(
    scheduler, sample_turn, turn_offset, monkeypatch
):
    released: list[tuple[object, object]] = []
    monkeypatch.setattr(
        scheduler,
        "_submit_tier_solve_locked",
        lambda binding, root_scope: released.append((binding, root_scope)),
    )
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
    binding = scheduler._stream_bindings[token]

    scheduler.begin_scope(_stream_scope(sample_turn, turn_offset=turn_offset))

    assert scheduler._globally_paused is False
    assert scheduler._held_initial_submissions == []
    assert scheduler._stream_bindings == {}
    assert released == [(binding, scores_root_scope_for_session(held))]
    for session in (bound, held):
        assert get_row_run_phase(session.run_id) is RowRunPhase.REGISTERED


SWITCHES: dict[str, Callable[[InferenceStreamScope], InferenceStreamScope]] = {
    "turn-switch": lambda scope: replace(scope, turn_number=scope.turn_number - 1),
    "perspective-switch": lambda scope: replace(scope, perspective=scope.perspective + 1),
}
switches = pytest.mark.parametrize("switch_to", SWITCHES.values(), ids=SWITCHES.keys())


def _walk_session(
    sample_turn, scheduler: InferenceRowScheduler, scores_rows, index: int = 0
) -> InferenceRowStreamSession:
    """A row session whose context lets the process orchestrator build its tier step."""
    session = _player_session(sample_turn, index)
    session.query_context = replace(
        session.query_context,
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(scheduler=scheduler, persistence=scores_rows)
        },
    )
    return session


@pytest.fixture
def walk_orchestrator(monkeypatch):
    """The process orchestrator on a pool with no workers, so a dispatched step stays running."""
    reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    return get_compute_orchestrator()


@pytest.fixture
def scores_rows() -> InferenceRowPersistenceService:
    return InferenceRowPersistenceService(MemoryAssetBackend(initial={}))


@switches
def test_a_walk_node_held_behind_pause_dispatches_when_a_switch_clears_pause(
    scheduler, sample_turn, walk_orchestrator, scores_rows, switch_to
):
    scope = _stream_scope(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    walk_session = _walk_session(sample_turn, scheduler, scores_rows)
    walk_node_scope = scores_root_scope_for_session(walk_session)
    walk_orchestrator.submit(
        ComputeRequest(
            scope=walk_node_scope, step_kind=SCORES_TIER_SOLVE, ctx=walk_session.query_context
        )
    )
    walk_orchestrator.dispatch_ready_work()
    assert walk_orchestrator.nodes[walk_node_scope].state == "ready"

    scheduler.begin_scope(switch_to(scope))

    assert walk_orchestrator.nodes[walk_node_scope].state == "running"


@switches
def test_rows_held_behind_pause_are_submitted_when_a_switch_clears_pause(
    scheduler, sample_turn, walk_orchestrator, scores_rows, switch_to
):
    scope = _stream_scope(sample_turn)
    token = scheduler.begin_scope(scope)
    rescheduled = _walk_session(sample_turn, scheduler, scores_rows, 0)
    rescheduled_node = scores_root_scope_for_session(rescheduled)
    assert (
        scheduler.enqueue_tier_ladder(rescheduled, stream_token=token)
        is TierLadderRegistration.STREAM_BOUND
    )
    scheduler.accept_pending_run(rescheduled.run_id)
    assert walk_orchestrator.nodes[rescheduled_node].state == "running"
    scheduler.pause_globally(scope)
    # A reschedule cancels the row, aborting its node, and registers a replacement.
    scheduler.cancel_row_run(rescheduled.run_id)
    assert walk_orchestrator.nodes[rescheduled_node].is_terminal
    replacement = _walk_session(sample_turn, scheduler, scores_rows, 0)
    admitted = _walk_session(sample_turn, scheduler, scores_rows, 1)
    admitted_node = scores_root_scope_for_session(admitted)
    for held in (replacement, admitted):
        assert (
            scheduler.enqueue_tier_ladder(held, stream_token=token) is TierLadderRegistration.HELD
        )

    scheduler.begin_scope(switch_to(scope))

    assert walk_orchestrator.nodes[rescheduled_node].state == "running"
    assert walk_orchestrator.nodes[admitted_node].state == "running"


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
