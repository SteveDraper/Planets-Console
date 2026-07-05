"""Shared table-stream session framework for per-player NDJSON multiplex streams."""

from api.streaming.table_stream.connect import (
    AdmissionDispatch,
    TableStreamConnectPolicy,
    iter_table_stream_connect,
)
from api.streaming.table_stream.errors import TableStreamScopeAlreadyActive
from api.streaming.table_stream.multiplex import (
    drain_available_multiplex_events,
    iter_multiplexed_stream_events,
)
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard

__all__ = [
    "AdmissionDispatch",
    "TableStreamConnectPolicy",
    "TableStreamScopeAlreadyActive",
    "TableStreamScopeGuard",
    "drain_available_multiplex_events",
    "iter_multiplexed_stream_events",
    "iter_table_stream_connect",
]
