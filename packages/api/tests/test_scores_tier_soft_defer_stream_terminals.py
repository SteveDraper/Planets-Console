"""Soft defer / stream terminal regressions for scores tier RowRun sharing."""

from __future__ import annotations

import queue

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    RowComplete,
    RowFailed,
)
from api.analytics.military_score_inference.inference_stream_rows import ScheduledInferenceRow
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.soft_stream_policy import SoftTerminalReason
from api.analytics.scores.tier_row_run_registry import (
    register_row_run,
)
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    get_stream_resolution,
)

from tests.scores_tier_cross_binding_test_helpers import (
    _scope_for,
    _session,
    _set_scope_node,
    _singleton_orchestrator,
    reset_cross_binding_registries,
)


@pytest.fixture(autouse=True)
def _reset_registries():
    with reset_cross_binding_registries():
        yield


def test_soft_row_defer_delivers_stream_terminal_without_completing_node(sample_turn) -> None:
    """Non-durable rowComplete defer soft-delivers without DAG complete (fleet blocked)."""
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    orchestrator = _singleton_orchestrator()
    soft_complete = row_complete_with_summary(
        InferenceResult(status="soft_partial", solutions=(), diagnostics={}),
        summary="soft defer",
    )
    _set_scope_node(
        orchestrator,
        scope,
        state="waiting_deps",
        priority_band="stream_attached",
        result_wire={"runId": run.run_id, "rowComplete": soft_complete},
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    scheduler.deliver_scores_row_defer_terminal(
        scope,
        soft_reason=SoftTerminalReason.NON_DURABLE_ROW_COMPLETE,
        event=soft_complete,
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    domain_terminals = [event for event in queued if isinstance(event, (RowComplete, RowFailed))]
    assert domain_terminals, (
        "soft defer left open stream without terminal "
        f"(session={session.run_id}, queued={queued!r})"
    )
    assert isinstance(domain_terminals[0], RowComplete)
    assert orchestrator.nodes[scope].state == "waiting_deps"
    soft_resolution = get_stream_resolution(session.run_id)
    assert soft_resolution is not None
    assert soft_resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL


def test_empty_park_schedule_row_stays_silent_for_wake(sample_turn) -> None:
    """Empty park with schedule-only row stays silent; wake owns progress (no RowFailed)."""
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    scheduler.deliver_scores_row_defer_terminal(
        scope,
        soft_reason=SoftTerminalReason.EMPTY_TIER_OUTCOME,
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    domain_terminals = [event for event in queued if isinstance(event, (RowComplete, RowFailed))]
    assert domain_terminals == []
    assert get_stream_resolution(session.run_id) is None


def test_soft_defer_revert_preserves_hard_terminal_claimed_during_admission(
    sample_turn, monkeypatch
) -> None:
    """Revert miss must not pop HARD_TERMINAL that landed between claim and pop."""
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    def _harden_then_miss(session_arg: InferenceRowStreamSession) -> bool:
        with scheduler._lock:
            delivery = scheduler._transition_stream_resolution_locked(
                session_arg.run_id,
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            )
        assert delivery is RowStreamDelivery.UPGRADE
        return False

    monkeypatch.setattr(controller, "push_admission_wire_terminal", _harden_then_miss)

    admitted = scheduler._admit_after_soft_provisional(scope, session, on_miss="revert")

    assert admitted is False
    hard_resolution = get_stream_resolution(session.run_id)
    assert hard_resolution is not None
    assert hard_resolution.state is RowStreamResolutionState.HARD_TERMINAL


def test_open_evidence_park_stays_silent_without_matching_row_run(sample_turn) -> None:
    """Open-evidence wait park must not soft-admit; wake owns progress."""
    session = _session(sample_turn)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    scheduler.deliver_scores_row_defer_terminal(
        scope,
        soft_reason=SoftTerminalReason.MISSING_ROW_RUN,
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    domain_terminals = [event for event in queued if isinstance(event, (RowComplete, RowFailed))]
    assert domain_terminals == []
    assert get_stream_resolution(session.run_id) is None


def test_missing_row_run_park_stays_silent_even_with_scheduler_run(
    sample_turn, monkeypatch
) -> None:
    """MISSING_ROW_RUN must not soft-admit just because the scheduler still tracks the scope."""
    from api.analytics.military_score_inference.inference_stream_rows import (
        ImmediateRowAdmission,
    )

    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    immediate = ImmediateRowAdmission(
        events=(
            {
                "type": "complete",
                "status": "exact",
                "summary": "should not admit",
                "isComplete": True,
                "playerId": session.player_id,
                "solutionCount": 0,
                "solutions": [],
            },
        ),
    )
    monkeypatch.setattr(
        controller,
        "resolve_row_admission",
        lambda _player_id, **_kwargs: immediate,
    )

    scheduler.deliver_scores_row_defer_terminal(
        scope,
        soft_reason=SoftTerminalReason.MISSING_ROW_RUN,
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    domain_terminals = [event for event in queued if isinstance(event, (RowComplete, RowFailed))]
    assert domain_terminals == []
    assert get_stream_resolution(session.run_id) is None
    assert not stream_drain.is_closed(session.run_id)


def test_empty_tier_park_cheap_admits_when_admission_available(sample_turn, monkeypatch) -> None:
    """EMPTY_TIER_OUTCOME soft-admits via cheap admission when available."""
    from api.analytics.military_score_inference.inference_stream_rows import (
        ImmediateRowAdmission,
    )

    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(session.player_id,),
        scheduler=scheduler,
        game_id=session.game_id,
        perspective=session.perspective,
    )
    controller.register_scheduled_row(
        session.player_id,
        ScheduledInferenceRow(player_id=session.player_id, session=session),
    )
    controller.attach()

    immediate = ImmediateRowAdmission(
        events=(
            {
                "type": "complete",
                "status": "exact",
                "summary": "empty park admission",
                "isComplete": True,
                "playerId": session.player_id,
                "solutionCount": 0,
                "solutions": [],
            },
        ),
    )
    monkeypatch.setattr(
        controller,
        "resolve_row_admission",
        lambda _player_id, **_kwargs: immediate,
    )

    scheduler.deliver_scores_row_defer_terminal(
        scope,
        soft_reason=SoftTerminalReason.EMPTY_TIER_OUTCOME,
    )

    soft_resolution = get_stream_resolution(session.run_id)
    assert soft_resolution is not None
    assert soft_resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL
    assert stream_drain.is_closed(session.run_id)
