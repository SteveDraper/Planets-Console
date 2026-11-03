"""Schedule admission paints a stored scoreboard row, or the absent signal when none is stored."""

from __future__ import annotations

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import fleet_evidence_mark_to_json
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    _TERMINAL_EVENT_TYPES,
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    ScheduleRowAdmission,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.streaming.table_stream import stream_drain
from api.transport.inference_stream import inference_no_stored_row_event

from tests.scores_exports_helpers import GAME_ID, minimal_stream_query_context


def _install_workerless_scheduler(monkeypatch: pytest.MonkeyPatch) -> InferenceRowScheduler:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)

    def _get_scheduler() -> InferenceRowScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler.get_inference_row_scheduler",
        _get_scheduler,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_rows.get_inference_row_scheduler",
        _get_scheduler,
    )
    return scheduler


def test_no_stored_row_event_names_the_missing_scoreboard_row() -> None:
    assert inference_no_stored_row_event() == {"type": "no_stored_row"}


def test_schedule_admission_yields_no_stored_row_before_deferred_submit(
    sample_turn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    submitted: list[str] = []

    def _record_submit(run_id: str) -> None:
        submitted.append(run_id)

    monkeypatch.setattr(scheduler, "accept_pending_run", _record_submit)

    player_id = sample_turn.scores[0].ownerid
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=scheduler,
        game_id=628580,
        perspective=1,
        query_context=minimal_stream_query_context(sample_turn),
    )

    scheduled = controller.dispatch_admission(player_id, ScheduleRowAdmission())
    assert submitted == []
    assert scheduled.defer_submit is not None
    assert scheduled.schedule_failed is False
    assert [event["type"] for event in scheduled.wire_events] == ["no_stored_row"]
    assert scheduled.wire_events[0]["playerId"] == player_id

    row = scheduled.scheduled
    assert row is not None
    scheduled.defer_submit()
    assert submitted == [row.session.run_id]

    immediate = controller.dispatch_admission(
        player_id,
        ImmediateRowAdmission(events=({"type": "complete", "status": "dead"},)),
    )
    assert immediate.defer_submit is None
    assert all(event.get("type") != "no_stored_row" for event in immediate.wire_events)

    cached = controller.dispatch_admission(
        player_id,
        CachedCompleteRowAdmission(event={"type": "complete", "status": "exact"}),
    )
    assert cached.defer_submit is None
    assert all(event.get("type") != "no_stored_row" for event in cached.wire_events)

    empty_cached = controller.dispatch_admission(
        player_id,
        CachedCompleteRowAdmission(event=None),
    )
    assert empty_cached.wire_events == ()

    controller.end_stream(scheduler)
    reset_inference_table_stream_registry_for_tests()


def _schedulable_player_ids(sample_turn) -> list[int]:
    found: list[int] = []
    for score in sample_turn.scores:
        admission = resolve_row_stream_admission(
            sample_turn,
            score.ownerid,
            game_id=GAME_ID,
            perspective=sample_turn.player.id,
            turn_number=sample_turn.settings.turn,
        )
        if isinstance(admission, ScheduleRowAdmission):
            found.append(score.ownerid)
    return found


def _context_with_marks(
    storage,
    sample_turn,
    *,
    player_ids: tuple[int, ...],
    mark: int,
    persistence,
):
    fleet_persistence = FleetSnapshotPersistenceService(storage)
    for player_id in player_ids:
        storage.put(
            fleet_persistence.evidence_mark_key(GAME_ID, sample_turn.player.id, player_id),
            fleet_evidence_mark_to_json(FleetEvidenceMark(evidence_generation=mark)),
        )
    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        game_id=GAME_ID,
        perspective=sample_turn.player.id,
        export_services={
            "fleet": FleetComputeServices(
                persistence=fleet_persistence,
                game_id=GAME_ID,
                perspective=sample_turn.player.id,
                load_turn=lambda turn_number: (
                    sample_turn if turn_number == sample_turn.settings.turn else None
                ),
            ),
            "scores": ScoresExportContext(persistence=persistence),
        },
    )


def test_force_schedule_while_a_row_is_stored_paints_that_row_and_keeps_the_run(
    sample_turn,
    persistence,
    memory_backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    submitted: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "accept_pending_run",
        lambda run_id: submitted.append(run_id),
    )

    player_ids = _schedulable_player_ids(sample_turn)
    assert len(player_ids) >= 2
    skip_player, success_player = player_ids[:2]
    turn = sample_turn.settings.turn
    perspective = sample_turn.player.id
    persistence.put_row(
        GAME_ID,
        perspective,
        turn,
        skip_player,
        PersistedInferenceRow(
            status="dead",
            summary="Player is dead",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    persistence.put_row(
        GAME_ID,
        perspective,
        turn,
        success_player,
        PersistedInferenceRow(
            status="exact",
            summary="Best build",
            solution_count=1,
            is_complete=True,
            solutions=[{"objectiveValue": 1, "actions": []}],
        ),
    )

    scope = InferenceStreamScope(
        game_id=GAME_ID,
        perspective=perspective,
        turn_number=turn,
    )
    stream_token = scheduler.begin_scope(scope)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(skip_player, success_player),
        scheduler=scheduler,
        game_id=GAME_ID,
        perspective=perspective,
        persistence=persistence,
        query_context=_context_with_marks(
            memory_backend,
            sample_turn,
            player_ids=(skip_player, success_player),
            mark=4,
            persistence=persistence,
        ),
    )

    skip_admission = controller.resolve_row_admission(skip_player, force_schedule=True)
    assert isinstance(skip_admission, ScheduleRowAdmission)
    skip_dispatch = controller.dispatch_admission(skip_player, skip_admission)
    assert skip_dispatch.defer_submit is not None
    assert skip_dispatch.scheduled is not None
    assert [event["type"] for event in skip_dispatch.wire_events] == ["stored_row"]
    skip_event = skip_dispatch.wire_events[0]
    assert skip_event["type"] not in _TERMINAL_EVENT_TYPES
    assert skip_event["status"] == "dead"
    assert skip_event["summary"] == "Player is dead"
    assert skip_event["solutionCount"] == 0
    assert skip_event["isComplete"] is True
    assert skip_event["evidenceGeneration"] == 0
    assert skip_event["evidenceMark"] == 4
    assert "displayStatus" not in skip_event
    skip_dispatch.defer_submit()
    skip_run_id = skip_dispatch.scheduled.session.run_id
    assert submitted == [skip_run_id]
    assert stream_drain.is_closed(skip_run_id) is False

    success_dispatch = controller.dispatch_admission(
        success_player,
        controller.resolve_row_admission(success_player, force_schedule=True),
    )
    assert success_dispatch.defer_submit is not None
    assert success_dispatch.scheduled is not None
    success_event = success_dispatch.wire_events[0]
    assert success_event["type"] == "stored_row"
    assert success_event["type"] not in _TERMINAL_EVENT_TYPES
    assert success_event["status"] == "exact"
    assert success_event["summary"] == "Best build"
    assert success_event["solutionCount"] == 1
    assert success_event["isComplete"] is True
    assert success_event["evidenceGeneration"] == 0
    assert success_event["evidenceMark"] == 4
    success_dispatch.defer_submit()
    success_run_id = success_dispatch.scheduled.session.run_id
    assert success_run_id in submitted
    assert stream_drain.is_closed(success_run_id) is False

    controller.end_stream(scheduler)
    reset_inference_table_stream_registry_for_tests()
