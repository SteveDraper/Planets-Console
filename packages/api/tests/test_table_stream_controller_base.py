"""TableStreamControllerBase: the roster a stream was opened for is fixed."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest
from api.streaming.table_stream.controller_base import TableStreamControllerBase


@dataclass(frozen=True)
class _Session:
    run_id: str


@dataclass(frozen=True)
class _ScheduledRow:
    session: _Session


def test_player_ids_cannot_be_reassigned_after_construction():
    controller = TableStreamControllerBase(stream_token="token", player_ids=(1, 2))

    with pytest.raises(FrozenInstanceError):
        controller.player_ids = (3,)

    assert controller.player_ids == (1, 2)


def test_scheduled_run_ids_are_in_roster_order_and_keep_the_scheduled_rows():
    controller = TableStreamControllerBase(stream_token="token", player_ids=(3, 1, 2))
    rows = {player_id: _ScheduledRow(_Session(f"run-{player_id}")) for player_id in (1, 3)}
    for player_id, row in rows.items():
        controller.register_scheduled_row(player_id, row)

    assert controller.scheduled_run_ids() == ("run-3", "run-1")
    assert controller.scheduled_rows == rows


def test_other_controller_state_stays_assignable():
    controller = TableStreamControllerBase(stream_token="token", player_ids=(1,))

    controller.pending_wire_events = [{"type": "x"}]

    assert controller.pending_wire_events == [{"type": "x"}]
