"""Route one table-stream terminal from delivery + multiplex_closed only."""

from __future__ import annotations

from enum import StrEnum

import api.streaming.table_stream.stream_drain as stream_drain
from api.streaming.table_stream.row_stream_resolution import RowStreamDelivery


class TerminalRoute(StrEnum):
    """Where an adapter should place a non-silenced terminal event."""

    QUEUE = "queue"
    PENDING = "pending"
    SILENCE = "silence"


def route_terminal(delivery: RowStreamDelivery, run_id: str) -> TerminalRoute:
    """Decide queue vs pending vs silence from delivery + ``multiplex_closed``.

    ``UPGRADE`` and drain-closed rows use pending wire (client already saw a
    provisional terminal, or multiplex already closed the queue slot).
    """
    if delivery is RowStreamDelivery.SILENCE:
        return TerminalRoute.SILENCE
    if delivery is RowStreamDelivery.UPGRADE or stream_drain.is_closed(run_id):
        return TerminalRoute.PENDING
    return TerminalRoute.QUEUE
