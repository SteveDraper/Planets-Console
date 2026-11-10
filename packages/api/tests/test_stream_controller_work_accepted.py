"""Controllers queue work_accepted on the scheduled row under the stream lock."""

from __future__ import annotations

import threading

from api.analytics.fleet.fleet_table_player_run import (
    FleetPlayerStreamSession,
    ScheduledFleetPlayer,
)
from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController
from api.analytics.military_score_inference.inference_stream_domain_events import WorkAccepted
from api.analytics.military_score_inference.inference_stream_rows import ScheduledInferenceRow
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.streaming.table_stream.controller_base import TableStreamControllerBase
from api.transport.fleet_table_stream import fleet_work_accepted_event
from api.transport.inference_stream_wire import domain_event_to_wire_events


class _RecordingLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self) -> _RecordingLock:
        self.held = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.held = False


class _RecordingQueue:
    def __init__(self, lock: _RecordingLock) -> None:
        self._lock = lock
        self.events: list[object] = []
        self.put_while_held = False

    def put(self, event: object) -> None:
        self.put_while_held = self._lock.held
        self.events.append(event)


class _RecordingSession:
    def __init__(self, event_queue: _RecordingQueue) -> None:
        self.event_queue = event_queue


class _RecordingRow:
    def __init__(self, session: _RecordingSession) -> None:
        self.session = session


def _controller_shell(controller_type):
    """Build a controller whose emit path only needs the base row lock."""
    controller = controller_type.__new__(controller_type)
    controller.stream_token = "work-accepted"
    controller.player_ids = ()
    controller.scheduled_rows = {}
    controller.pending_wire_events = []
    controller.stream_lock = threading.Lock()
    controller.wake_multiplex = threading.Event()
    return controller


def test_enqueue_on_scheduled_row_holds_the_stream_lock_during_the_put() -> None:
    lock = _RecordingLock()
    event_queue = _RecordingQueue(lock)
    controller = TableStreamControllerBase(
        stream_token="work-accepted",
        player_ids=(4,),
        stream_lock=lock,
    )
    controller.register_scheduled_row(4, _RecordingRow(_RecordingSession(event_queue)))

    controller.enqueue_on_scheduled_row(
        4, lambda row: row.session.event_queue.put({"type": "work_accepted"})
    )

    assert event_queue.put_while_held is True
    assert event_queue.events == [{"type": "work_accepted"}]
    assert controller.wake_multiplex.is_set()

    controller.wake_multiplex.clear()
    controller.enqueue_on_scheduled_row(
        9, lambda row: row.session.event_queue.put({"type": "work_accepted"})
    )
    assert event_queue.events == [{"type": "work_accepted"}]
    assert controller.wake_multiplex.is_set() is False


def test_fleet_emit_work_accepted_queues_the_fleet_event(sample_turn) -> None:
    player_id = sample_turn.player.id
    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=sample_turn,
        game_id=1,
        perspective=1,
    )
    controller = _controller_shell(FleetTableStreamController)
    controller.register_scheduled_row(
        player_id,
        ScheduledFleetPlayer(player_id=player_id, session=session),
    )

    controller.emit_work_accepted(player_id)

    assert session.event_queue.get_nowait() == fleet_work_accepted_event()
    assert controller.wake_multiplex.is_set()


def test_inference_emit_work_accepted_queues_the_domain_event(sample_turn) -> None:
    player_id = sample_turn.player.id
    observation = InferenceObservation(
        player_id=player_id,
        turn=sample_turn.settings.turn,
        military_delta_2x=0,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=0,
        is_after_ship_limit=False,
    )
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=observation,
        turn=sample_turn,
        game_id=1,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    controller = _controller_shell(InferenceTableStreamController)
    controller.register_scheduled_row(
        player_id,
        ScheduledInferenceRow(player_id=player_id, session=session),
    )

    controller.emit_work_accepted(player_id)

    event = session.event_queue.get_nowait()
    assert isinstance(event, WorkAccepted)
    assert domain_event_to_wire_events(
        event,
        observation=session.observation,
        turn=session.turn,
    ) == [{"type": "work_accepted"}]
    assert controller.wake_multiplex.is_set()
