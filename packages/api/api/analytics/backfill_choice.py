"""Resolve Backfill earlier turns once for one query context.

The export walk, catalog, and compute DAG take that bool. They do not read
the record and they do not import fleet services. Missing fleet services have
no record to read, so the choice is off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.fleet.constants import ANALYTIC_ID

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


def backfill_earlier_turns_for_context(ctx: AnalyticQueryContext) -> bool:
    """Read Backfill earlier turns once for the game on this query context."""
    service = ctx.export_services.get(ANALYTIC_ID)
    persistence = getattr(service, "persistence", None)
    reader = getattr(persistence, "backfill_earlier_turns_enabled", None)
    if not callable(reader):
        return False
    return reader(ctx.game_id)
