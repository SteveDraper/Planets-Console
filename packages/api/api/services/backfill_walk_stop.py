"""Stopping every accepted Backfill earlier turns walk in one game.

The walk in game G is its non-terminal on-walk fleet and scoreboard nodes, in
every perspective. :func:`stop_backfill_walks` settles them through
:class:`WalkStopPolicy` and leaves every other node in G alone. The stop is
stateless and writes nothing durable: a stopped walk is its failed nodes, which
a later on-walk submit replaces. A row still live on G (a second tab, or a
stop that arrives late) has its own root stopped too; the stop's follow-up
reschedules it, which submits that replacement.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from api.analytics.fleet_walk_analytics import (
    FLEET_WALK_ANALYTIC_IDS,
    WALK_ANALYTIC_RUNNING_DISPOSITION,
)
from api.analytics.walk_row_reschedule import reschedule_walk_rows, rows_with_stopped_scope
from api.analytics.walk_shell_watch import live_walk_shells
from api.compute.in_flight_settle import (
    GameWork,
    InFlightCandidate,
    InFlightSettlePolicy,
    RunningDisposition,
    UnstartedDisposition,
)
from api.compute.scope import ComputeScope
from api.services.in_flight_orchestrator import InFlightOrchestrator

WalkStopFollowUp: TypeAlias = Callable[[], None]
"""What a stop leaves to run off the response path: its drain, then its row reschedules."""


@dataclass(frozen=True)
class WalkStopPolicy(InFlightSettlePolicy):
    """What a stop does to one fleet or scoreboard node of the game.

    On the walk, a node no worker has picked is aborted, and a running node
    takes its analytic's walk disposition. A node off the walk is kept.
    """

    def unstarted(self, candidate: InFlightCandidate) -> UnstartedDisposition:
        if candidate.submission_open.on_walk:
            return UnstartedDisposition.ABORT
        return UnstartedDisposition.KEEP

    def running(self, candidate: InFlightCandidate) -> RunningDisposition:
        if candidate.submission_open.on_walk:
            return WALK_ANALYTIC_RUNNING_DISPOSITION[candidate.scope.analytic_id]
        return RunningDisposition.KEEP


def stop_backfill_walks(orchestrator: InFlightOrchestrator, game_id: int) -> WalkStopFollowUp:
    """Stop every accepted walk in ``game_id``, in every perspective.

    Settles under the orchestrator lock and returns, without running it, the
    stop's follow-up. The stamped scoreboard cancel and the abort listeners run
    only in the follow-up's drain, so the caller must run it, off any response
    path.
    """
    stopped = orchestrator.settle_in_flight_work(
        GameWork(game_id=game_id, analytic_ids=FLEET_WALK_ANALYTIC_IDS),
        WalkStopPolicy(),
    )

    def follow_up() -> None:
        _drain_then_reschedule_stopped_rows(orchestrator, stopped)

    return follow_up


def _drain_then_reschedule_stopped_rows(
    orchestrator: InFlightOrchestrator,
    stopped: frozenset[ComputeScope],
) -> None:
    """Drain what the stop queued, then reschedule the live rows whose own scope it stopped.

    The drain runs first so each row's abort listeners have run before its
    reschedule cancels and re-admits it. The live rows are scanned after the
    drain, so a row that closed meanwhile is not rescheduled.
    """
    orchestrator.drain_post_lock_callbacks()
    reschedule_walk_rows(rows_with_stopped_scope(stopped, live_walk_shells()))
