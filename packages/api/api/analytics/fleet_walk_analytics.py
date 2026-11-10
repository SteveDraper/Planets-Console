"""Analytics that take part in the fleet ledger walk."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID

# Analytics whose compute nodes and live table streams carry a submission's
# backfill choice: the fleet ledger walk and the scoreboard solves it feeds.
FLEET_WALK_ANALYTIC_IDS = frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID})
