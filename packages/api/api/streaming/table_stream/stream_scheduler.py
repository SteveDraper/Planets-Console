"""What a table-stream connect needs from its scheduler."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from api.streaming.table_stream.off_lock_runner import OffLockRunner

ScopeT = TypeVar("ScopeT", contravariant=True)


@runtime_checkable
class TableStreamScheduler(Protocol[ScopeT]):
    """Claims a stream's scope and ends the stream, on the scheduler's own runner.

    ``end_table_stream`` takes the scope and token positionally; the connect
    posts it to ``off_lock_runner``, so the end and the runner that runs it
    always come from the same scheduler.
    """

    off_lock_runner: OffLockRunner

    def begin_scope(self, scope: ScopeT) -> str: ...

    def end_table_stream(self, scope: ScopeT, stream_token: str, /) -> None: ...
