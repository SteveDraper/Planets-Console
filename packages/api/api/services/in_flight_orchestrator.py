"""The orchestrator surface services use to read, settle and drain in-flight work.

``ComputeOrchestrator`` satisfies :class:`InFlightOrchestrator` structurally.
When this process has not created an orchestrator, :func:`in_flight_orchestrator`
returns a stand-in that has no in-flight work, so a caller never starts the
worker pool just to find nothing there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeAlias

from api.compute.in_flight_settle import InFlightSettlePolicy, InFlightWork
from api.compute.orchestrator import ComputeOrchestrator, OpenTurnRoot
from api.compute.runtime import peek_compute_orchestrator


class InFlightOrchestrator(Protocol):
    """The orchestrator queries, settle and drain that services use for in-flight work.

    The absent-process stand-in subclasses it, so its signatures are checked
    against this one.
    """

    def open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
        turn: int | None = None,
    ) -> tuple[OpenTurnRoot, ...]: ...

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
    ) -> None: ...

    def drain_post_lock_callbacks(self) -> None: ...


PostLockDrain: TypeAlias = Callable[[], None]
"""One orchestrator's ``drain_post_lock_callbacks``, bound by the service that settled on it."""


class _AbsentProcessOrchestrator(InFlightOrchestrator):
    """Stand-in when this process has not created an orchestrator.

    There is then no in-flight work. Creating the real orchestrator would
    start a worker pool, so root queries are empty, and settle and drain
    are no-ops.
    """

    def open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
        turn: int | None = None,
    ) -> tuple[OpenTurnRoot, ...]:
        return ()

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
    ) -> None:
        return

    def drain_post_lock_callbacks(self) -> None:
        return


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
