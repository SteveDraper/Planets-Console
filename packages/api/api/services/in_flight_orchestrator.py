"""The orchestrator surface services use for in-flight work and after-root-plans work.

Services read, settle and drain in-flight work through it, and hand it work
that must wait until no root plan is open on their thread.

``ComputeOrchestrator`` satisfies :class:`InFlightOrchestrator` structurally.
When this process has not created an orchestrator, :func:`in_flight_orchestrator`
returns a stand-in that has no in-flight work, so a caller never starts the
worker pool just to find nothing there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeAlias

from api.callback_containment import run_contained
from api.compute.in_flight_settle import InFlightSettlePolicy, InFlightWork
from api.compute.orchestrator import ComputeOrchestrator, OpenTurnRoot
from api.compute.runtime import peek_compute_orchestrator
from api.compute.scope import ComputeScope


class InFlightOrchestrator(Protocol):
    """The orchestrator queries, settle, drain and after-root-plans run that services use.

    The absent-process stand-in subclasses it, so its signatures are checked
    against this one.
    """

    def claim_open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        open_turn: int,
        analytic_ids: frozenset[str],
    ) -> tuple[OpenTurnRoot, ...]: ...

    def settle_in_flight_work(
        self,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
        *,
        then: Callable[[], None] | None = None,
    ) -> frozenset[ComputeScope]: ...

    def drain_post_lock_callbacks(self) -> None: ...

    def run_after_root_plans(self, callback: Callable[[], None]) -> None: ...


class _AbsentProcessOrchestrator(InFlightOrchestrator):
    """Stand-in when this process has not created an orchestrator.

    There is then no in-flight work. Creating the real orchestrator would
    start a worker pool, so root queries are empty, a settle stops nothing
    but still runs its ``then``, and a drain does nothing. No root plan can
    be open without an orchestrator, so after-root-plans work runs at once,
    contained.
    """

    def claim_open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        open_turn: int,
        analytic_ids: frozenset[str],
    ) -> tuple[OpenTurnRoot, ...]:
        return ()

    def settle_in_flight_work(
        self,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
        *,
        then: Callable[[], None] | None = None,
    ) -> frozenset[ComputeScope]:
        if then is not None:
            then()
        return frozenset()

    def drain_post_lock_callbacks(self) -> None:
        return

    def run_after_root_plans(self, callback: Callable[[], None]) -> None:
        run_contained(callback, "After-root-plans callback")


_ABSENT_PROCESS_ORCHESTRATOR = _AbsentProcessOrchestrator()

OrchestratorResolver: TypeAlias = Callable[[], ComputeOrchestrator | None]


def in_flight_orchestrator(
    orchestrator: ComputeOrchestrator | None,
) -> InFlightOrchestrator:
    """Process orchestrator, or a stand-in when none exists yet."""
    if orchestrator is None:
        return _ABSENT_PROCESS_ORCHESTRATOR
    return orchestrator


def process_in_flight_orchestrator() -> InFlightOrchestrator:
    """This process's orchestrator if it has created one, else the stand-in."""
    return in_flight_orchestrator(peek_compute_orchestrator())
