"""How far a running node's execution may go past the step a worker picked.

``ComputeNodeRun.running_step`` holds a :class:`RunningStepDisposition`. A
settle only raises it, so the lattice order is the order of restriction. Only
a root attach lowers it, and only from ``END_AFTER_STEP`` to ``CONTINUE``.
:meth:`RunningStepDisposition.permits` is the one table of which step exits
each disposition lets the execution take, and
:meth:`RunningStepDisposition.refusal_error` the one table of what a refused
execution fails with.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum, IntEnum
from types import MappingProxyType

from api.compute.errors import ComputeScopeAbortedError
from api.exceptions import DiscardedWorkRefused


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
    NO = "no"
    WHILE_NEEDED = "while_needed"


class RunningStepDisposition(IntEnum):
    """What a settle left a running execution allowed to do, least restrictive first.

    ``CONTINUE``: unrestricted. ``END_AFTER_STEP``: the picked step
    finishes, persists and completes, and the execution then starts or
    requeues no further step unless non-terminal work still needs it.
    ``FINISH_WITHOUT_STAMP``: the picked step's worker finishes, and the
    execution then ends without persisting, stamping, completing or running
    again.
    """

    CONTINUE = 0
    END_AFTER_STEP = 1
    FINISH_WITHOUT_STAMP = 2

    def permits(self, step_exit: StepExit, *, is_needed: Callable[[], bool]) -> bool:
        """Whether this execution may take ``step_exit``.

        ``is_needed`` derives whether non-terminal work the orchestrator keeps
        alive still depends on this node. Only a ``WHILE_NEEDED`` cell calls
        it, so a caller pays for that derivation only when the answer
        depends on it.
        """
        permit = _PERMITS[self][step_exit]
        return permit is _Permit.YES or (permit is _Permit.WHILE_NEEDED and is_needed())

    @property
    def permits_no_exit(self) -> bool:
        """Whether this execution may take no exit at all once its picked step finishes.

        Such an execution ends whatever its step returned, so its result
        need not be read to refuse it.
        """
        return all(permit is _Permit.NO for permit in _PERMITS[self].values())

    def refusal_error(self) -> BaseException:
        """The error an execution this disposition refuses fails with.

        ``FINISH_WITHOUT_STAMP`` fails with ``DiscardedWorkRefused``, which
        dependents inherit. ``END_AFTER_STEP`` fails with
        ``ComputeScopeAbortedError``, which they do not, so a later submit
        replaces the node. ``CONTINUE`` refuses no exit and has no entry.
        """
        return _REFUSAL_ERROR[self]()

    def lowered_by_root_attach(self) -> RunningStepDisposition:
        """The disposition after a submit attaches to the node as its root.

        The attach makes the node needed again, so ``END_AFTER_STEP`` lowers
        to ``CONTINUE``. ``FINISH_WITHOUT_STAMP`` is never lowered: that
        execution must not stamp, whoever joins it.
        """
        if self is RunningStepDisposition.END_AFTER_STEP:
            return RunningStepDisposition.CONTINUE
        return self


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
        RunningStepDisposition.FINISH_WITHOUT_STAMP: MappingProxyType(
            {
                StepExit.PERSIST: _Permit.NO,
                StepExit.COMPLETE: _Permit.NO,
                StepExit.START: _Permit.NO,
                StepExit.REQUEUE: _Permit.NO,
            }
        ),
    }
)

_REFUSAL_ERROR: Mapping[RunningStepDisposition, Callable[[], BaseException]] = MappingProxyType(
    {
        RunningStepDisposition.END_AFTER_STEP: lambda: ComputeScopeAbortedError(
            "a stopped execution that nothing needs does not start or requeue a step"
        ),
        RunningStepDisposition.FINISH_WITHOUT_STAMP: lambda: DiscardedWorkRefused(
            "discarded step does not persist or stamp the new evidence mark"
        ),
    }
)
