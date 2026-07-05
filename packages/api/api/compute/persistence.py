"""Per-analytic persistence hooks for the compute orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.scope import ComputeScope


class PersistencePolicy(Protocol):
    """Analytic-owned cache schema, write gates, merge, and invalidation."""

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        """Return whether the scope already has a durable satisfied result."""
        ...

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> None:
        """Persist a completed result wire after orchestrator epoch checks."""
        ...

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        """Drop or bump cached state for one compute scope."""
        ...
