"""Schedule admission paints that no scoreboard row is stored before submit."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    ScheduleRowAdmission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.transport.inference_stream import inference_no_stored_row_event

from tests.scores_exports_helpers import minimal_stream_query_context


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

    monkeypatch.setattr(scheduler, "perform_deferred_tier_submit", _record_submit)

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
