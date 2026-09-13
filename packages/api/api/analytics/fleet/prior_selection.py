"""Shared prior-ledger selection for fleet job-wire and scores tier-wire."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.types import PersistedFleetLedger


def select_fleet_prior_persisted(
    *,
    from_dependency_outputs: PersistedFleetLedger | None,
    from_disk: PersistedFleetLedger | None,
) -> PersistedFleetLedger | None:
    """Choose the prior ledger for fleet@N / scores@N+1 job-wire assembly.

    In-run ``DependencyOutputs`` is preferred when it already carries a final
    prior (or when disk has nothing better). A non-final DepOutputs prior must
    not override a final disk ledger -- that orphans refined recordIds and is
    the Cyborg turn-5 identity-loss fingerprint.
    """
    if from_dependency_outputs is not None and from_dependency_outputs.provenance.is_final:
        return from_dependency_outputs
    if from_disk is not None and from_disk.provenance.is_final:
        return from_disk
    if from_dependency_outputs is not None:
        return from_dependency_outputs
    return from_disk


def resolve_fleet_prior_persisted(
    *,
    from_dependency_outputs: PersistedFleetLedger | None,
    load_from_disk: Callable[[], PersistedFleetLedger | None],
) -> PersistedFleetLedger | None:
    """Select a prior ledger, reading disk only when DepOutputs is not already final."""
    if from_dependency_outputs is not None and from_dependency_outputs.provenance.is_final:
        return from_dependency_outputs
    return select_fleet_prior_persisted(
        from_dependency_outputs=from_dependency_outputs,
        from_disk=load_from_disk(),
    )
