"""Shared table-stream session framework for per-player NDJSON multiplex streams."""

from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.connect import (
    AdmissionDispatch,
    TableStreamConnectPolicy,
    iter_table_stream_connect,
)
from api.streaming.table_stream.multiplex import (
    drain_available_multiplex_events,
    iter_multiplexed_stream_events,
)
from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolution,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_stream_resolutions,
    discard_stream_resolution_if_state,
    get_stream_resolution,
    reset_stream_resolution_registry_for_tests,
    transition_stream_resolution,
)
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard
from api.streaming.table_stream.terminal_route import TerminalRoute, route_terminal

__all__ = [
    "AdmissionDispatch",
    "RowStreamDelivery",
    "RowStreamResolution",
    "RowStreamResolutionState",
    "RowStreamResolutionTrigger",
    "TableStreamConnectPolicy",
    "TableStreamScopeGuard",
    "TerminalRoute",
    "clear_stream_resolutions",
    "discard_stream_resolution_if_state",
    "drain_available_multiplex_events",
    "get_stream_resolution",
    "iter_multiplexed_stream_events",
    "iter_table_stream_connect",
    "reset_stream_resolution_registry_for_tests",
    "route_terminal",
    "stream_drain",
    "transition_stream_resolution",
]
