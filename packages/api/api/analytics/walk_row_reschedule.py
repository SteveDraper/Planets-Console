"""Rescheduling the live walk rows whose own work a settle stopped.

A settle that stops a live row's root node, or limits it to end after its
step, leaves that row with no work to finish it. Its fleet or scoreboard
listener treats the resulting abort as intentional and paints no error, so
whoever settled reschedules the row through its stream controller. The
controller cancels the row's run and re-admits it, which submits the
replacement work.
"""

from __future__ import annotations

from collections.abc import Iterable

from api.analytics.walk_shell_watch import LiveWalkShell
from api.compute.scope import ComputeScope


def has_stopped_scope(row: LiveWalkShell, stopped: frozenset[ComputeScope]) -> bool:
    """Whether ``row``'s own root scope is in ``stopped``."""
    return row.own_scope in stopped


def rows_with_stopped_scope(
    stopped: frozenset[ComputeScope],
    live_rows: Iterable[LiveWalkShell],
) -> tuple[LiveWalkShell, ...]:
    """The live rows whose own root scope is in ``stopped``."""
    return tuple(row for row in live_rows if has_stopped_scope(row, stopped))


def reschedule_walk_rows(rows: Iterable[LiveWalkShell]) -> None:
    """Reschedule each row through its stream controller.

    Runs outside every orchestrator and stream lock: a reschedule cancels and
    submits.
    """
    for row in rows:
        row.stream.controller.reschedule_player(row.key.player_id)
