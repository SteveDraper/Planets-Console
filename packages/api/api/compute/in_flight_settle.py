"""What a settle selects and what its caller's policy decides for each node.

``ComputeOrchestrator.settle_in_flight_work`` applies these under the
orchestrator lock. The selection and the dispositions are plain values, so
``compute/`` holds no analytic or caller knowledge: which work to select is
the caller's :data:`InFlightWork`, and what happens to each selected node is
its :class:`InFlightSettlePolicy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


class UnstartedDisposition(Enum):
    """What a settle does to a selected node no worker is running.

    ``ABORT`` aborts it with ``ComputeScopeAbortedError``, which its
    dependents do not inherit, so a later submit replaces it. An aborted node
    that live work still needs is kept.
    """

    KEEP = "keep"
    ABORT = "abort"


class RunningDisposition(Enum):
    """What a settle does to a selected running node.

    ``ABORT`` aborts the execution as ``UnstartedDisposition.ABORT`` does,
    and is likewise kept when live work still needs the node.
    ``END_AFTER_STEP`` raises the node's ``running_step`` to
    ``RunningStepDisposition.END_AFTER_STEP``.
    """

    KEEP = "keep"
    ABORT = "abort"
    END_AFTER_STEP = "end_after_step"


@dataclass(frozen=True)
class GameWork:
    """Every perspective's and player's work in one game, for these analytics."""

    game_id: int
    analytic_ids: frozenset[str]

    def selects(self, scope: ComputeScope) -> bool:
        return scope.analytic_id in self.analytic_ids and scope.game_id == self.game_id


@dataclass(frozen=True)
class PlayerWork:
    """One player's work in one game perspective, for these analytics."""

    game_id: int
    perspective: int
    player_id: int
    analytic_ids: frozenset[str]

    def selects(self, scope: ComputeScope) -> bool:
        return (
            scope.analytic_id in self.analytic_ids
            and scope.game_id == self.game_id
            and scope.perspective == self.perspective
            and scope.player_id == self.player_id
        )


InFlightWork: TypeAlias = GameWork | PlayerWork


@dataclass(frozen=True)
class InFlightCandidate:
    """The read-only view of one selected non-terminal node a policy decides on."""

    scope: ComputeScope
    submission_open: SubmissionOpen


class InFlightSettlePolicy(Protocol):
    """Decides each selected node's disposition. Policies subclass this explicitly.

    Both methods run under the orchestrator lock. They must not re-enter the
    orchestrator.
    """

    def unstarted(self, candidate: InFlightCandidate) -> UnstartedDisposition: ...

    def running(self, candidate: InFlightCandidate) -> RunningDisposition: ...
