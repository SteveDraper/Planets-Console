"""Process-wide compute scope lease for cross-binding singleflight.

Per-stream / warm ``ComputeOrchestrator`` bindings each own a DAG. The same
logical ``(ComputeScope, step_kind)`` can become ready on multiple bindings
(fleet stream, scores stream, background warm). This lease ensures at most one
leader executes expensive work process-wide; followers park and resume after
the leader releases.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from api.compute.pools import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.scope import ComputeScope

ClaimOutcome = Literal["acquired", "parked"]

WakeCallback = Callable[[], None]


@dataclass(frozen=True)
class ScopeStepClaimKey:
    """Identity for one process-wide compute claim."""

    scope: ComputeScope
    step_kind: str


@dataclass
class _LeaseWaiter:
    orchestrator_id: int
    priority_band: ComputePriorityBand
    on_wake: WakeCallback


@dataclass
class _LeaseClaim:
    orchestrator_id: int
    priority_band: ComputePriorityBand
    waiters: list[_LeaseWaiter] = field(default_factory=list)


class ProcessWideScopeLease:
    """Claim table keyed by normalized compute scope + step kind."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claims: dict[ScopeStepClaimKey, _LeaseClaim] = {}

    def try_acquire(
        self,
        key: ScopeStepClaimKey,
        *,
        orchestrator_id: int,
        priority_band: ComputePriorityBand,
        on_wake: WakeCallback,
    ) -> ClaimOutcome:
        """Acquire the claim or park as a waiter until the leader releases."""
        with self._lock:
            claim = self._claims.get(key)
            if claim is None:
                self._claims[key] = _LeaseClaim(
                    orchestrator_id=orchestrator_id,
                    priority_band=priority_band,
                )
                return "acquired"
            if claim.orchestrator_id == orchestrator_id:
                return "acquired"
            self._upsert_waiter(
                claim,
                orchestrator_id=orchestrator_id,
                priority_band=priority_band,
                on_wake=on_wake,
            )
            return "parked"

    def release(
        self,
        key: ScopeStepClaimKey,
        *,
        orchestrator_id: int,
    ) -> tuple[WakeCallback, ...]:
        """Release a held claim and return wake callbacks (highest priority first).

        No-op when ``orchestrator_id`` does not hold the claim. Waiters are sorted
        by priority band so stream-attached bindings resume before background warm.
        """
        with self._lock:
            claim = self._claims.get(key)
            if claim is None or claim.orchestrator_id != orchestrator_id:
                return ()
            waiters = sorted(
                claim.waiters,
                key=lambda waiter: PRIORITY_BAND_RANK[waiter.priority_band],
            )
            del self._claims[key]
            return tuple(waiter.on_wake for waiter in waiters)

    def release_all_for_orchestrator(
        self,
        orchestrator_id: int,
    ) -> tuple[WakeCallback, ...]:
        """Release every claim held by ``orchestrator_id`` (binding teardown)."""
        with self._lock:
            held_keys = [
                key
                for key, claim in self._claims.items()
                if claim.orchestrator_id == orchestrator_id
            ]
            wake_callbacks: list[WakeCallback] = []
            for key in held_keys:
                claim = self._claims.pop(key)
                waiters = sorted(
                    claim.waiters,
                    key=lambda waiter: PRIORITY_BAND_RANK[waiter.priority_band],
                )
                wake_callbacks.extend(waiter.on_wake for waiter in waiters)
            return tuple(wake_callbacks)

    def holder(
        self,
        key: ScopeStepClaimKey,
    ) -> tuple[int, ComputePriorityBand] | None:
        """Return ``(orchestrator_id, priority_band)`` when the claim is held."""
        with self._lock:
            claim = self._claims.get(key)
            if claim is None:
                return None
            return claim.orchestrator_id, claim.priority_band

    def reset_for_tests(self) -> None:
        """Drop all claims (tests only)."""
        with self._lock:
            self._claims.clear()

    @staticmethod
    def _upsert_waiter(
        claim: _LeaseClaim,
        *,
        orchestrator_id: int,
        priority_band: ComputePriorityBand,
        on_wake: WakeCallback,
    ) -> None:
        for index, waiter in enumerate(claim.waiters):
            if waiter.orchestrator_id == orchestrator_id:
                claim.waiters[index] = _LeaseWaiter(
                    orchestrator_id=orchestrator_id,
                    priority_band=priority_band,
                    on_wake=on_wake,
                )
                return
        claim.waiters.append(
            _LeaseWaiter(
                orchestrator_id=orchestrator_id,
                priority_band=priority_band,
                on_wake=on_wake,
            )
        )


_PROCESS_SCOPE_LEASE = ProcessWideScopeLease()


def get_process_scope_lease() -> ProcessWideScopeLease:
    """Return the process-wide scope lease singleton."""
    return _PROCESS_SCOPE_LEASE


def reset_process_scope_lease_for_tests() -> None:
    """Clear process-wide lease state (tests only)."""
    _PROCESS_SCOPE_LEASE.reset_for_tests()
