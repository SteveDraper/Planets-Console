"""Stopping every accepted Backfill earlier turns walk in one game.

The walk in game G is its non-terminal on-walk fleet and scoreboard nodes, in
every perspective. :func:`stop_backfill_walks` settles them through
:class:`WalkStopPolicy` and leaves every other node in G alone. The stop is
stateless and writes nothing durable: a stopped walk is its failed nodes, which
a later on-walk submit replaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet_walk_analytics import (
    FLEET_WALK_ANALYTIC_IDS,
    WALK_ANALYTIC_RUNNING_DISPOSITION,
)
from api.compute.in_flight_settle import (
    GameWork,
    InFlightCandidate,
    InFlightSettlePolicy,
    RunningDisposition,
    UnstartedDisposition,
)
from api.services.in_flight_orchestrator import InFlightOrchestrator


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


def stop_backfill_walks(orchestrator: InFlightOrchestrator, game_id: int) -> None:
    """Stop every accepted walk in ``game_id``, in every perspective.

    Only settles, under the orchestrator lock. The caller drains the post-lock
    work it queues (``InFlightOrchestrator.drain_post_lock_callbacks``).
    """
    orchestrator.settle_in_flight_work(
        GameWork(game_id=game_id, analytic_ids=FLEET_WALK_ANALYTIC_IDS),
        WalkStopPolicy(),
    )
