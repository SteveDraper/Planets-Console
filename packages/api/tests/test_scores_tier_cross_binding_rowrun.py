"""Regression: shared RowRun must survive first peer binding completion."""

from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
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
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    unregister_row_run,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope


@pytest.fixture(autouse=True)
def _reset_registries():
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()


def _session(sample_turn) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
    )


def _scope_for(session: InferenceRowStreamSession) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )


def _singleton_orchestrator():
    return get_compute_orchestrator()


def _set_scope_node(
    orchestrator,
    scope: ComputeScope,
    *,
    state: str,
    priority_band: str = "background",
    **kwargs: object,
) -> ComputeNodeRun:
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state=state,
        priority_band=priority_band,
        **kwargs,
    )
    orchestrator._nodes[scope] = node
    return node


def test_run_scores_tier_solve_continues_when_rowrun_unregistered(sample_turn) -> None:
    """Missing RowRun must park (rebuild wire on wake), not empty-complete and unlock fleet."""
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    unregister_row_run(run.run_id)

    result = run_scores_tier_solve({"runId": run.run_id})

    assert result.outcome == "park"


def test_run_scores_tier_solve_skip_sentinel_requires_evidence_closed_marker() -> None:
    assert run_scores_tier_solve({"runId": None, "evidenceClosed": True}).outcome == "complete"
    assert run_scores_tier_solve({"runId": None}).outcome == "park"


def test_first_peer_complete_keeps_rowrun_while_sibling_running(sample_turn, monkeypatch) -> None:
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
        "api.analytics.military_score_inference.inference_scheduler."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact",
    )
    completed_node = SimpleNamespace(
        state="complete",
        result_wire={"runId": run.run_id, "rowComplete": row_complete},
        error=None,
    )

    scheduler._on_orchestrator_node_complete(scope, completed_node)

    assert get_row_run(run.run_id) is run
    assert run.run_id in scheduler._runs
    assert len(delivered) == 1

    orchestrator._nodes[scope].state = "complete"
    scheduler._on_orchestrator_node_complete(scope, completed_node)

    assert get_row_run(run.run_id) is None
    assert run.run_id not in scheduler._runs
    assert len(delivered) == 1


def test_peer_failure_does_not_unregister_while_sibling_running(sample_turn, monkeypatch) -> None:
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
        "api.analytics.military_score_inference.inference_scheduler."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    failed_node = SimpleNamespace(
        state="failed",
        result_wire={"runId": run.run_id},
        error=RuntimeError("peer boom"),
    )
    scheduler._on_orchestrator_node_complete(scope, failed_node)

    assert get_row_run(run.run_id) is run
    assert delivered == []


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
        "api.analytics.military_score_inference.inference_scheduler."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

    assert get_row_run(run.run_id) is run
    assert delivered == []

    orchestrator._nodes[scope].state = "complete"
    orchestrator._nodes[scope].result_wire = {"exportTree": {"ok": True}}
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

    assert delivered, (
        "last peer empty-complete left DAG terminal without a stream terminal "
        f"(delivered={delivered!r})"
    )
    assert get_row_run(run.run_id) is None


def test_orphan_empty_node_complete_delivers_terminal_to_open_stream(
    sample_turn,
) -> None:
    """Regression: DAG terminal after idempotent empty complete must finish open stream.

    Cross-binding race: peer finalizes/unregisters the shared RowRun (and scheduler
    ``_runs`` entry) without a stream terminal, then the other binding's
    ``tier_solve`` returns idempotent ``complete`` with no ``rowComplete``. The
    orchestrator node is terminal, but ``_on_orchestrator_node_complete`` finds no
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

    # Premature unregister: RowRun gone and scheduler no longer tracks the run,
    # but the open stream session still exists (UI in-progress / last event progress).
    unregister_row_run(run.run_id)
    assert get_row_run(run.run_id) is None
    assert scheduler._runs == {}
    assert session.player_id in controller.scheduled_rows
    assert session.run_id not in controller.finished_run_ids

    # Missing RowRun parks until force_fresh wake can rebuild wire / reschedule.
    assert run_scores_tier_solve({"runId": run.run_id}).outcome == "park"

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

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


def test_late_peer_empty_complete_does_not_clobber_prior_row_complete(
    sample_turn,
) -> None:
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
    success_node = SimpleNamespace(
        state="complete",
        result_wire={"runId": run.run_id, "rowComplete": row_complete},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, success_node)
    assert get_row_run(run.run_id) is None
    assert run.run_id in scheduler._terminal_stream_events_delivered

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

    queued: list[object] = []
    while True:
        try:
            queued.append(session.event_queue.get_nowait())
        except queue.Empty:
            break
    assert len([e for e in queued if isinstance(e, RowComplete)]) == 1
    assert [e for e in queued if isinstance(e, RowFailed)] == []


def test_empty_complete_delivers_to_stream_session_not_ensure_session(
    sample_turn,
) -> None:
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

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

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


def test_stale_scheduler_run_without_registry_still_finishes_stream(
    sample_turn,
) -> None:
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

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

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
    sample_turn,
    monkeypatch,
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

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

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
    assert session.run_id in controller.finished_run_ids
    assert get_row_run(run.run_id) is None


def test_orphan_terminal_reaches_pending_wire_when_finished_without_client_event(
    sample_turn,
) -> None:
    """Cancel-silent finished_run_ids must not suppress the orphan stream terminal.

    Multiplex can mark a run finished when the cancel token trips without yielding a
    wire event. Orphan delivery used to bail on finished_run_ids and leave the
    scoreboard in-progress while the DAG was already complete.
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
    controller.finished_run_ids.add(session.run_id)
    controller.attach()

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

    pending = controller.drain_pending_wire_events()
    assert any(event.get("type") in {"complete", "error"} for event in pending), (
        f"expected pending-wire terminal after finished_run_ids suppress, got {pending!r}"
    )


def test_row_complete_upgrades_prior_empty_admission_terminal(
    sample_turn,
    monkeypatch,
) -> None:
    """Regression: force_fresh RowComplete must upgrade a soft empty/admission terminal.

    Fingerprint (game 628580 t8 Fury): evidenceClosed skip empty-completes and pushes
    admission wire (multiplex finished_run_ids), then force_fresh re-solves. Without
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

    empty_complete = SimpleNamespace(
        state="complete",
        result_wire={"exportTree": {"ok": True}},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, empty_complete)

    assert session.run_id in scheduler._terminal_stream_events_delivered
    assert session.run_id in scheduler._upgradable_empty_terminals
    assert session.run_id in controller.finished_run_ids

    # Simulate force_fresh re-solve: reopen multiplex drain, then deliver RowComplete.
    scheduler._reopen_stream_row_for_force_fresh(scope)
    assert session.run_id not in controller.finished_run_ids

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
    success_node = SimpleNamespace(
        state="complete",
        result_wire={"runId": run.run_id, "rowComplete": row_complete},
        error=None,
    )
    scheduler._on_orchestrator_node_complete(scope, success_node)

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
    assert session.run_id not in scheduler._upgradable_empty_terminals
