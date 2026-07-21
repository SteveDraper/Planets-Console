"""Per-analytic persistence hooks for the compute orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


@dataclass(frozen=True)
class PersistDependencyRecovery:
    """Demote the persisting node to ``waiting_deps`` and optionally re-submit a dependency.

    Analytic ``PersistencePolicy.persist`` raises :class:`PersistDeferredError`
    carrying this when a durable write cannot complete until another scope is
    re-run (typically ``force_fresh``). The orchestrator handles the signal
    generically -- no analytic ids or feature exceptions in the shared path.
    This is a real dependency wait, not soft ``parked`` / outcome ``park``.
    """

    dependency_scope: ComputeScope
    force_fresh: bool = True
    step_kind: str | None = None


class PersistDeferredError(Exception):
    """Raised from ``PersistencePolicy.persist`` when the write must wait on a dependency.

    The orchestrator demotes the node to ``waiting_deps`` (not ``failed``, not
    soft ``parked``), grafts ``recovery.dependency_scope`` onto the node's
    dependency edges when missing, and, when ``recovery.force_fresh`` is true,
    submits that scope so a durable dependency close can wake rematerialization.
    """

    def __init__(self, message: str, *, recovery: PersistDependencyRecovery) -> None:
        super().__init__(message)
        self.recovery = recovery


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

        May raise :class:`PersistDeferredError` when the durable write cannot
        complete until a dependency is force-freshed; the orchestrator demotes
        the node to ``waiting_deps`` and applies ``recovery`` generically.
        """
        ...

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        """Drop or bump cached state for one compute scope."""
        ...

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        """Return the current invalidation epoch for one compute scope."""
        ...
