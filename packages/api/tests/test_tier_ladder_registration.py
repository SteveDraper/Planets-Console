"""``enqueue_tier_ladder`` decides stream ownership once and always registers the RowRun."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    TierLadderRegistration,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import ScheduleRowAdmission
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.compute_orchestration import build_scores_tier_solve_job_wire
from api.analytics.scores.export_snapshot import scores_inference_stream_scope
from api.analytics.scores.exports import admit_scores_export_work
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.streaming.table_stream.row_run_admission import RowRunPhase

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.scores_exports_helpers import (
    GAME_ID,
    inference_target_player_id,
    minimal_stream_query_context,
)
from tests.scores_row_lifecycle_test_helpers import _session_for_player
from tests.submission_open_helpers import explicit_submission_open

PERSPECTIVE = 1


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()


def _stream_scope(sample_turn, *, perspective: int = PERSPECTIVE) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=GAME_ID,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
    )


def _record_background_wakes(
    monkeypatch: pytest.MonkeyPatch,
    scheduler: InferenceRowScheduler,
) -> list[ComputeScope]:
    woken: list[ComputeScope] = []
    monkeypatch.setattr(
        scheduler,
        "_wake_deferred_scores_after_row_run_adopt",
        lambda root_scope, _session: woken.append(root_scope),
    )
    return woken


def _record_tier_submits(
    monkeypatch: pytest.MonkeyPatch,
    scheduler: InferenceRowScheduler,
) -> list[ComputeScope]:
    submitted: list[ComputeScope] = []
    monkeypatch.setattr(
        scheduler,
        "_submit_tier_solve_locked",
        lambda _binding, root_scope: submitted.append(root_scope),
    )
    return submitted


def _switch_scope_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    scheduler: InferenceRowScheduler,
    switch_to: InferenceStreamScope,
) -> None:
    """Another stream takes the scheduler between the caller's token and the enqueue."""
    enqueue = scheduler.enqueue_tier_ladder

    def switch_then_enqueue(session, **kwargs) -> TierLadderRegistration:
        scheduler.begin_scope(switch_to)
        return enqueue(session, **kwargs)

    monkeypatch.setattr(scheduler, "enqueue_tier_ladder", switch_then_enqueue)


def test_an_owning_stream_token_binds_the_run(sample_turn, monkeypatch):
    scheduler = InferenceRowScheduler()
    woken = _record_background_wakes(monkeypatch, scheduler)
    submitted = _record_tier_submits(monkeypatch, scheduler)
    token = scheduler.begin_scope(_stream_scope(sample_turn))
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)

    registration = scheduler.enqueue_tier_ladder(session, stream_token=token)
    scheduler.accept_pending_run(session.run_id)

    assert registration is TierLadderRegistration.STREAM_BOUND
    assert woken == []
    assert submitted == [scheduler._runs[session.run_id]]


def test_no_stream_registers_a_background_run_and_wakes_its_scope(sample_turn, monkeypatch):
    scheduler = InferenceRowScheduler()
    woken = _record_background_wakes(monkeypatch, scheduler)
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)

    registration = scheduler.enqueue_tier_ladder(session)

    assert registration is TierLadderRegistration.BACKGROUND
    assert woken == [scheduler._runs[session.run_id]]


def test_a_paused_stream_holds_the_submission(sample_turn, monkeypatch):
    scheduler = InferenceRowScheduler()
    woken = _record_background_wakes(monkeypatch, scheduler)
    scope = _stream_scope(sample_turn)
    token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)

    registration = scheduler.enqueue_tier_ladder(session, stream_token=token)

    assert registration is TierLadderRegistration.HELD
    assert woken == []
    assert [held.root_scope for held in scheduler._held_initial_submissions] == [
        scheduler._runs[session.run_id]
    ]


def test_a_submit_deferred_scheduler_only_registers_the_run(sample_turn, monkeypatch):
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    woken = _record_background_wakes(monkeypatch, scheduler)
    token = scheduler.begin_scope(_stream_scope(sample_turn))
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)

    registration = scheduler.enqueue_tier_ladder(session, stream_token=token)

    assert registration is TierLadderRegistration.SUBMIT_DEFERRED
    assert woken == []
    assert scheduler.row_run_for_player(_stream_scope(sample_turn), session.player_id) is not None


def test_connect_admission_that_loses_the_scope_registers_one_background_run(
    sample_turn,
    monkeypatch,
):
    scheduler = InferenceRowScheduler()
    woken = _record_background_wakes(monkeypatch, scheduler)
    submitted = _record_tier_submits(monkeypatch, scheduler)
    player_id = inference_target_player_id(sample_turn)
    scope = _stream_scope(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=scheduler,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        query_context=minimal_stream_query_context(sample_turn),
    )
    _switch_scope_before_enqueue(
        monkeypatch,
        scheduler,
        replace(scope, turn_number=scope.turn_number - 1),
    )

    dispatch = controller.dispatch_admission(player_id, ScheduleRowAdmission())

    assert dispatch.schedule_failed
    assert dispatch.scheduled is None
    run = scheduler.row_run_for_player(scope, player_id)
    assert run is not None
    assert run.phase is RowRunPhase.REGISTERED
    assert list(scheduler._runs) == [run.run_id]
    assert controller.scheduled_rows == {}
    assert woken == [scheduler._runs[run.run_id]]
    scheduler.accept_pending_run(run.run_id)
    assert submitted == []


def test_admit_whose_stream_token_loses_the_scope_still_runs_the_hop(
    sample_turn,
    persistence,
    monkeypatch,
):
    scheduler = InferenceRowScheduler()
    woken = _record_background_wakes(monkeypatch, scheduler)
    player_id = inference_target_player_id(sample_turn)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=sample_turn.player.id,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    export_scope = ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=player_id,
    )
    stream_scope = scores_inference_stream_scope(export_scope)
    stream_token = scheduler.begin_scope(stream_scope)
    ctx = replace(
        ctx,
        export_services={
            **ctx.export_services,
            "scores": replace(
                ctx.export_services["scores"],
                resolve_stream_token=lambda _scope: stream_token,
            ),
        },
    )
    _switch_scope_before_enqueue(
        monkeypatch,
        scheduler,
        replace(stream_scope, turn_number=stream_scope.turn_number - 1),
    )

    assert admit_scores_export_work(
        ctx,
        export_scope,
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

    run = scheduler.row_run_for_player(stream_scope, player_id)
    assert run is not None
    assert run.phase is RowRunPhase.REGISTERED
    assert woken == [scope]

    wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
        submission_open=explicit_submission_open(),
        execution_generation=1,
    )

    assert wire["runId"] == run.run_id
