"""Process-wide compute scope lease for cross-binding singleflight.

Per-stream / warm ``ComputeOrchestrator`` bindings each own a DAG. The same
logical ``(ComputeScope, step_kind)`` can become ready on multiple bindings
(fleet stream, scores stream, background warm). This lease ensures at most one
leader executes expensive work process-wide; followers park and resume after
the leader releases.

Priority preference: while a claim is held but not yet sealed for execution, a
strictly higher ``priority_band`` **adopts** (e.g. ``stream_attached`` takes the
claim from ``background``). The demoted holder discovers the loss at
``seal_for_execution`` and parks. Once sealed, the leader runs to completion
(no mid-execution preempt).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from api.compute.pools import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.scope import ComputeScope

ClaimOutcome = Literal["acquired", "parked", "adopted"]
SealOutcome = Literal["sealed", "lost"]

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
    leader_on_wake: WakeCallback
    waiters: list[_LeaseWaiter] = field(default_factory=list)
    execution_started: bool = False


@dataclass(frozen=True)
class SealResult:
    """Outcome of sealing a held claim for expensive work."""

    outcome: SealOutcome


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
        """Acquire the claim, adopt from a lower-priority unsealed holder, or park."""
        with self._lock:
            claim = self._claims.get(key)
            if claim is None:
                self._claims[key] = _LeaseClaim(
                    orchestrator_id=orchestrator_id,
                    priority_band=priority_band,
                    leader_on_wake=on_wake,
                )
                return "acquired"
            if claim.orchestrator_id == orchestrator_id:
                claim.leader_on_wake = on_wake
                claim.priority_band = priority_band
                return "acquired"
            if (
                not claim.execution_started
                and PRIORITY_BAND_RANK[priority_band]
                < PRIORITY_BAND_RANK[claim.priority_band]
            ):
                # Transfer leadership only. The demoted holder is still on its
                # execute path and re-parks (or short-circuits) at seal.
                claim.orchestrator_id = orchestrator_id
                claim.priority_band = priority_band
                claim.leader_on_wake = on_wake
                return "adopted"
            self._upsert_waiter(
                claim,
                orchestrator_id=orchestrator_id,
                priority_band=priority_band,
                on_wake=on_wake,
            )
            return "parked"

    def seal_for_execution(
        self,
        key: ScopeStepClaimKey,
        *,
        orchestrator_id: int,
    ) -> SealResult:
        """Mark a held claim past the adopt-safe point, or report loss.

        Call immediately before expensive work (inline ``run_step`` or pool
        submit). Returns ``sealed`` when the caller still holds the claim, or
        ``lost`` when a higher-priority peer adopted it away.
        """
        with self._lock:
            claim = self._claims.get(key)
            if claim is None or claim.orchestrator_id != orchestrator_id:
                return SealResult(outcome="lost")
            claim.execution_started = True
            return SealResult(outcome="sealed")

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

    def is_execution_started(self, key: ScopeStepClaimKey) -> bool:
        """Return True when the claim is held and sealed for expensive work."""
        with self._lock:
            claim = self._claims.get(key)
            return claim is not None and claim.execution_started

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
