"""Analytics that take part in the fleet ledger walk."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.in_flight_settle import RunningDisposition

# What a stopped walk does to its running node of each walk analytic. A
# picked fleet step finishes and persists, and the node then ends unless
# something still needs it. A running scoreboard solve aborts and does not
# persist.
WALK_ANALYTIC_RUNNING_DISPOSITION: Mapping[str, RunningDisposition] = MappingProxyType(
    {
        FLEET_ANALYTIC_ID: RunningDisposition.END_AFTER_STEP,
        SCORES_ANALYTIC_ID: RunningDisposition.ABORT,
    }
)

# Analytics whose compute nodes and live table streams carry a submission's
# backfill choice: the fleet ledger walk and the scoreboard solves it feeds.
FLEET_WALK_ANALYTIC_IDS = frozenset(WALK_ANALYTIC_RUNNING_DISPOSITION)
