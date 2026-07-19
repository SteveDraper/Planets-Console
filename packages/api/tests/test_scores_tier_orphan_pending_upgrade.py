"""Orphan / pending / upgrade regressions for scores tier stream terminals."""

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
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    register_row_run,
    retire_row_run,
)
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_stream_resolution import (
    RowStreamResolutionState,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    get_stream_resolution,
)

from tests.scores_tier_cross_binding_test_helpers import (
    _outcome_snapshot,
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


def test_empty_peer_complete_then_last_peer_empty_delivers_terminal(
    sample_turn, monkeypatch
) -> None:
    """Both bindings can terminal-complete without rowComplete; stream must still get a terminal.

    Materialize→continue leaves ``exportTree`` on ``result_wire``. Idempotent / skip
    ``tier_solve`` then completes with no payload, so the node stays complete with no
    ``rowComplete``. First peer must not drop the open stream on the floor while a
    sibling is live; the last peer must still deliver a terminal domain event.
    """
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="running",
        priority_band="stream_attached",
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[run.run_id] = scope

    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_resolution."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    assert get_row_run(run.run_id) is run
    assert delivered == []

    orchestrator._nodes[scope].state = "complete"
    orchestrator._nodes[scope].result_wire = {"exportTree": {"ok": True}}
    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"exportTree": {"ok": True}},
        ),
    )

    assert delivered, (
        "last peer empty-complete left DAG terminal without a stream terminal "
        f"(delivered={delivered!r})"
    )
    assert get_row_run(run.run_id) is None


def test_orphan_empty_node_complete_delivers_terminal_to_open_stream(sample_turn) -> None:
    """Regression: DAG terminal after idempotent empty complete must finish open stream.

    Cross-binding race: peer finalizes/retires the shared RowRun (and scheduler
    ``_runs`` entry) without a stream terminal, then the other binding's
    ``tier_solve`` returns idempotent ``complete`` with no ``rowComplete``. The
    orchestrator node is terminal, but ``_on_orchestrator_scope_outcome`` finds no
    matching run_id. Orphan fallback must still deliver a terminal so multiplex does
    not stay on ``progress``.
    """
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
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
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

    # Premature retire: RowRun gone and scheduler no longer tracks the run,
    # but the open stream session still exists (UI in-progress / last event progress).
    retire_row_run(run.run_id)
    assert get_row_run(run.run_id) is None
    assert scheduler._runs == {}
    assert session.player_id in controller.scheduled_rows
    assert not stream_drain.is_closed(session.run_id)

    # Missing RowRun parks until force_fresh wake can rebuild wire / reschedule.
    assert run_scores_tier_solve({"runId": run.run_id}).outcome == "park"

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    domain_terminals = [event for event in queued if isinstance(event, (RowComplete, RowFailed))]
    assert domain_terminals, (
        "orchestrator node complete after idempotent empty tier_solve with no "
        f"matching scheduler run left open stream without terminal "
        f"(session={session.run_id}, queued={queued!r})"
    )
    assert isinstance(domain_terminals[0], RowFailed)


def test_late_peer_empty_complete_does_not_clobber_prior_row_complete(sample_turn) -> None:
    """After a successful peer delivery+finalize, a late empty peer must not RowFailed."""
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
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
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

    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact",
    )
    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"runId": run.run_id, "rowComplete": row_complete},
        ),
    )
    assert get_row_run(run.run_id) is None
    resolution = get_stream_resolution(run.run_id)
    assert resolution is not None
    assert resolution.state is RowStreamResolutionState.HARD_TERMINAL

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    assert len([e for e in queued if isinstance(e, RowComplete)]) == 1
    assert [e for e in queued if isinstance(e, RowFailed)] == []


def test_empty_complete_delivers_to_stream_session_not_ensure_session(sample_turn) -> None:
    """Regression: DAG complete with no rowComplete must finish the multiplex session.

    Background/ensure can register a different ``RowRun`` session than the table stream
    adopted. Delivering only to the ensure session leaves multiplex waiting on the
    stream session -- UI stays in-progress with idle CPU (manual hang fingerprint).
    """
    ensure_session = _session(sample_turn)
    stream_session = _session(sample_turn)
    assert ensure_session.run_id != stream_session.run_id
    assert ensure_session.player_id == stream_session.player_id

    run = RowRun(ensure_session)
    register_row_run(run)
    scope = _scope_for(ensure_session)
    stream_scope = InferenceStreamScope(
        game_id=stream_session.game_id,
        perspective=stream_session.perspective,
        turn_number=stream_session.turn_number,
    )

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    scheduler._runs[run.run_id] = scope
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(stream_session.player_id,),
        scheduler=scheduler,
        game_id=stream_session.game_id,
        perspective=stream_session.perspective,
    )
    controller.register_scheduled_row(
        stream_session.player_id,
        ScheduledInferenceRow(player_id=stream_session.player_id, session=stream_session),
    )
    controller.attach()

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    ensure_queued: list[object] = []
    while True:
        try:
            ensure_queued.append(ensure_session.event_queue.get_nowait())
        except queue.Empty:
            break
    stream_queued: list[object] = []
    while True:
        try:
            stream_queued.append(stream_session.event_queue.get_nowait())
        except queue.Empty:
            break

    assert not any(isinstance(e, (RowComplete, RowFailed)) for e in ensure_queued)
    stream_terminals = [e for e in stream_queued if isinstance(e, (RowComplete, RowFailed))]
    assert stream_terminals, (
        "empty tier_solve complete left stream session without terminal "
        f"(ensure_queued={ensure_queued!r}, stream_queued={stream_queued!r})"
    )
    assert isinstance(stream_terminals[0], RowFailed)


def test_stale_scheduler_run_without_registry_still_finishes_stream(sample_turn) -> None:
    """Stale ``_runs`` entry with no registry RowRun must not skip stream terminal."""
    session = _session(sample_turn)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    stale_run_id = "stale-run-without-registry"
    scheduler._runs[stale_run_id] = scope
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

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    terminals = [e for e in queued if isinstance(e, (RowComplete, RowFailed))]
    assert terminals, f"stale _runs skip left stream without terminal (queued={queued!r})"
    assert stale_run_id not in scheduler._runs


def test_matching_run_empty_complete_uses_admission_before_row_failed(
    sample_turn, monkeypatch
) -> None:
    """Matching-run empty complete must try admission before RowFailed (orphan parity)."""
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

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
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
        events=({"type": "complete", "status": "noPriorTurn", "playerId": session.player_id},),
    )
    monkeypatch.setattr(
        controller,
        "resolve_row_admission",
        lambda _player_id, **_kwargs: immediate,
    )

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    assert [e for e in queued if isinstance(e, RowFailed)] == []
    pending = controller.drain_pending_wire_events()
    assert any(event.get("type") == "complete" for event in pending), (
        f"expected admission complete on pending wire, got pending={pending!r} queued={queued!r}"
    )
    assert stream_drain.is_closed(session.run_id)
    assert get_row_run(run.run_id) is None


def test_orphan_terminal_reaches_pending_wire_when_finished_without_client_event(
    sample_turn,
) -> None:
    """Cancel-silent drain close must not suppress the orphan stream terminal.

    Multiplex can close drain when the cancel token trips without yielding a
    wire event. Orphan delivery must still reach pending wire via multiplex_closed.
    """
    session = _session(sample_turn)
    scope = _scope_for(session)
    stream_scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
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
    # Cancel-silent multiplex finish closes drain; emit routes from multiplex_closed.
    stream_drain.close(session.run_id)
    controller.attach()

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    pending = controller.drain_pending_wire_events()
    assert any(event.get("type") in {"complete", "error"} for event in pending), (
        f"expected pending-wire terminal after drain close, got {pending!r}"
    )


def test_row_complete_upgrades_prior_empty_admission_terminal(sample_turn, monkeypatch) -> None:
    """Regression: force_fresh RowComplete must upgrade a soft empty/admission terminal.

    Fingerprint (game 628580 t8 Fury): evidenceClosed skip empty-completes and pushes
    admission wire (multiplex_closed drain), then force_fresh re-solves. Without
    upgrade the real RowComplete is dropped, progress resets the UI, and the scoreboard
    stays in-progress with idle CPU.
    """
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

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"exportTree": {"ok": True}},
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
                "summary": "cached",
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

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(scope, state="complete", result_wire={"exportTree": {"ok": True}}),
    )

    soft_resolution = get_stream_resolution(session.run_id)
    assert soft_resolution is not None
    assert soft_resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL
    assert stream_drain.is_closed(session.run_id)

    # Simulate force_fresh re-solve: reopen multiplex drain, then deliver RowComplete.
    scheduler._reopen_stream_row_for_force_fresh(scope)
    assert not stream_drain.is_closed(session.run_id)

    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact after force_fresh",
    )
    register_row_run(run)
    scheduler._runs[run.run_id] = scope
    _set_scope_node(
        orchestrator,
        scope,
        state="complete",
        priority_band="stream_attached",
        result_wire={"runId": run.run_id, "rowComplete": row_complete},
    )
    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"runId": run.run_id, "rowComplete": row_complete},
        ),
    )

    pending = controller.drain_pending_wire_events()
    upgrades = [
        event
        for event in pending
        if event.get("type") == "complete" and event.get("summary") == "exact after force_fresh"
    ]
    assert upgrades, (
        "expected RowComplete upgrade on pending wire after soft empty admission "
        f"(pending={pending!r})"
    )
    hard_resolution = get_stream_resolution(session.run_id)
    assert hard_resolution is not None
    assert hard_resolution.state is RowStreamResolutionState.HARD_TERMINAL
