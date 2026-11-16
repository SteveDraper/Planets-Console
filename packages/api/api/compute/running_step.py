"""How far a running node's execution may go past the step a worker picked.

``ComputeNodeRun.running_step`` holds a :class:`RunningStepDisposition`. A
settle only raises it, from ``CONTINUE`` to ``END_AFTER_STEP``, and only a
root attach lowers it back. :meth:`RunningStepDisposition.permits` is the one
table of which step exits each disposition lets the execution take.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum, IntEnum
from types import MappingProxyType


class StepExit(Enum):
    """A point where a running execution goes on past its picked step."""

    PERSIST = "persist"
    COMPLETE = "complete"
    # Start a step: a pool pick, an inline start, or a continue into the next step.
    START = "start"
    # Re-enter dispatch: epoch retry, persist-deferred recovery, soft waiting_deps, park.
    REQUEUE = "requeue"


class _Permit(Enum):
    YES = "yes"
    WHILE_NEEDED = "while_needed"


class RunningStepDisposition(IntEnum):
    """What a settle left a running execution allowed to do, least restrictive first.

    ``CONTINUE``: unrestricted. ``END_AFTER_STEP``: the picked step
    finishes, persists and completes, and the execution then starts or
    requeues no further step unless non-terminal work still needs it.
    """

    CONTINUE = 0
    END_AFTER_STEP = 1

    def permits(self, step_exit: StepExit, *, is_needed: Callable[[], bool]) -> bool:
        """Whether this execution may take ``step_exit``.

        ``is_needed`` derives whether non-terminal work the orchestrator keeps
        alive still depends on this node. Only a ``WHILE_NEEDED`` cell calls
        it, so a caller pays for that derivation only when the answer
        depends on it.
        """
        permit = _PERMITS[self][step_exit]
        return permit is _Permit.YES or (permit is _Permit.WHILE_NEEDED and is_needed())


_PERMITS: Mapping[RunningStepDisposition, Mapping[StepExit, _Permit]] = MappingProxyType(
    {
        RunningStepDisposition.CONTINUE: MappingProxyType(
            {
                StepExit.PERSIST: _Permit.YES,
                StepExit.COMPLETE: _Permit.YES,
                StepExit.START: _Permit.YES,
                StepExit.REQUEUE: _Permit.YES,
            }
        ),
        RunningStepDisposition.END_AFTER_STEP: MappingProxyType(
            {
                StepExit.PERSIST: _Permit.YES,
                StepExit.COMPLETE: _Permit.YES,
                StepExit.START: _Permit.WHILE_NEEDED,
                StepExit.REQUEUE: _Permit.WHILE_NEEDED,
            }
        ),
    }
)
