"""TableStreamControllerBase: the roster a stream was opened for is fixed."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from api.streaming.table_stream.controller_base import TableStreamControllerBase


def test_player_ids_cannot_be_reassigned_after_construction():
    controller = TableStreamControllerBase(stream_token="token", player_ids=(1, 2))

    with pytest.raises(FrozenInstanceError):
        controller.player_ids = (3,)

    assert controller.player_ids == (1, 2)


def test_other_controller_state_stays_assignable():
    controller = TableStreamControllerBase(stream_token="token", player_ids=(1,))

    controller.pending_wire_events = [{"type": "x"}]

    assert controller.pending_wire_events == [{"type": "x"}]
