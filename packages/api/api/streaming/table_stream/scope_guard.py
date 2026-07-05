"""Composable table-stream scope ownership for per-turn NDJSON multiplex streams."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Generic, TypeVar

ScopeT = TypeVar("ScopeT")


class TableStreamScopeGuard(Generic[ScopeT]):
    """Tracks active table-stream scope and token; call methods under the scheduler lock."""

    def __init__(self) -> None:
        self._active_scope: ScopeT | None = None
        self._has_active_table_stream = False
        self._active_table_stream_token: str | None = None

    @property
    def active_scope(self) -> ScopeT | None:
        return self._active_scope

    @property
    def has_active_table_stream(self) -> bool:
        return self._has_active_table_stream

    @property
    def active_table_stream_token(self) -> str | None:
        return self._active_table_stream_token

    def begin_scope_locked(
        self,
        scope: ScopeT,
        *,
        on_same_scope_preempt: Callable[[], None],
        on_scope_change: Callable[[], None],
    ) -> str:
        if self._active_scope == scope and self._has_active_table_stream:
            on_same_scope_preempt()
        elif self._active_scope != scope:
            on_scope_change()
            self._active_scope = scope
        stream_token = str(uuid.uuid4())
        self._has_active_table_stream = True
        self._active_table_stream_token = stream_token
        return stream_token

    def owns_table_stream_locked(self, stream_token: str) -> bool:
        return self._active_table_stream_token == stream_token

    def active_scope_matches_locked(self, scope: ScopeT) -> bool:
        return self._active_scope == scope

    def end_table_stream_locked(self, scope: ScopeT, stream_token: str) -> bool:
        """Clear scope ownership when token matches. Returns whether this call owned the scope."""
        owns = self._active_table_stream_token == stream_token
        if owns and self._active_scope == scope:
            self._has_active_table_stream = False
            self._active_table_stream_token = None
        return owns

    def preempt_locked(self, *, on_preempt: Callable[[], None]) -> None:
        on_preempt()
        self._has_active_table_stream = False
        self._active_table_stream_token = None
