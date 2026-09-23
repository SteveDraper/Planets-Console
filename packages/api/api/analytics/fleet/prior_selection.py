"""Shared prior-ledger selection for fleet job-wire and scores tier-wire."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.types import PersistedFleetLedger


def select_fleet_prior_persisted(
    *,
    from_dependency_outputs: PersistedFleetLedger | None,
    load_from_disk: Callable[[], PersistedFleetLedger | None],
    is_ensure_final: Callable[[PersistedFleetLedger], bool] | None = None,
) -> PersistedFleetLedger | None:
    """Choose the prior ledger for fleet@N / scores@N+1 job-wire assembly.

    In-run ``DependencyOutputs`` is preferred when it already carries a final
    prior (or when disk has nothing better). A non-final DepOutputs prior must
    not override a final disk ledger -- that orphans refined recordIds and is
    the Cyborg turn-5 identity-loss fingerprint.

    ``load_from_disk`` runs only when DepOutputs is missing or not ensure-final.
    ``is_ensure_final`` defaults to provenance ``(true, true)``. Callers that
    have an evidence mark pass a check that also requires generation agreement.
    """
    ensure_final = is_ensure_final or (lambda persisted: persisted.provenance.is_final)
    if from_dependency_outputs is not None and ensure_final(from_dependency_outputs):
        return from_dependency_outputs
    from_disk = load_from_disk()
    if from_disk is not None and ensure_final(from_disk):
        return from_disk
    if from_dependency_outputs is not None:
        return from_dependency_outputs
    return from_disk


def resolve_fleet_prior_persisted(
    *,
    from_dependency_outputs: PersistedFleetLedger | None,
    load_from_disk: Callable[[], PersistedFleetLedger | None],
    is_ensure_final: Callable[[PersistedFleetLedger], bool] | None = None,
) -> PersistedFleetLedger | None:
    """Select a prior ledger, reading disk only when DepOutputs is not already final."""
    return select_fleet_prior_persisted(
        from_dependency_outputs=from_dependency_outputs,
        load_from_disk=load_from_disk,
        is_ensure_final=is_ensure_final,
    )
