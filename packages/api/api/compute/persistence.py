"""Per-analytic persistence hooks for the compute orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.scope import ComputeScope


class PersistencePolicy(Protocol):
    """Analytic-owned cache schema, write gates, merge, and invalidation."""

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        """Return whether the scope already has a durable satisfied result."""
        ...

    def satisfied_result_wire(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
    ) -> object | None:
        """Result wire for satisfaction short-circuit, or None for ``{}``.

        When durable satisfaction holds, dependents and stream listeners may need a
        real wire (e.g. fleet ``persistedLedgerWire``). Return None only when the
        analytic has no wire shape for a cheap complete.
        """
        ...

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> Callable[[], None] | None:
        """Persist a completed result wire after orchestrator epoch checks.

        The orchestrator invokes this **outside** its lock, but **before** marking
        the node ``complete``. Callers that observe terminal node state or run
        after node-complete listeners may assume durable artifacts already exist.

        Return an optional side-effect callback (e.g. ledger-persisted notification)
        to run after the node has been marked complete and the orchestrator lock
        is released again.
        """
        ...

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        """Drop or bump cached state for one compute scope."""
        ...

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        """Return the current invalidation epoch for one compute scope."""
        ...
