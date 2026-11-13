"""The running-step lattice and what each disposition permits."""

from __future__ import annotations

import pytest
from api.compute.running_step import RunningStepDisposition, StepExit

_CONTINUE = RunningStepDisposition.CONTINUE
_FINISH_WITHOUT_STAMP = RunningStepDisposition.FINISH_WITHOUT_STAMP


@pytest.mark.parametrize(
    ("disposition", "step_exit", "permitted"),
    [
        (_CONTINUE, StepExit.PERSIST, True),
        (_CONTINUE, StepExit.COMPLETE, True),
        (_CONTINUE, StepExit.START, True),
        (_CONTINUE, StepExit.REQUEUE, True),
        (_FINISH_WITHOUT_STAMP, StepExit.PERSIST, False),
        (_FINISH_WITHOUT_STAMP, StepExit.COMPLETE, False),
        (_FINISH_WITHOUT_STAMP, StepExit.START, False),
        (_FINISH_WITHOUT_STAMP, StepExit.REQUEUE, False),
    ],
)
@pytest.mark.parametrize("is_needed", [True, False])
def test_permits(
    disposition: RunningStepDisposition,
    step_exit: StepExit,
    permitted: bool,
    is_needed: bool,
) -> None:
    assert disposition.permits(step_exit, is_needed=lambda: is_needed) is permitted


@pytest.mark.parametrize("disposition", list(RunningStepDisposition))
@pytest.mark.parametrize("step_exit", list(StepExit))
def test_needed_is_derived_only_when_the_answer_depends_on_it(
    disposition: RunningStepDisposition,
    step_exit: StepExit,
) -> None:
    derivations: list[bool] = []

    def needed(answer: bool):
        def derive() -> bool:
            derivations.append(answer)
            return answer

        return derive

    while_needed = disposition.permits(step_exit, is_needed=needed(True))
    while_unneeded = disposition.permits(step_exit, is_needed=needed(False))

    assert bool(derivations) == (while_needed != while_unneeded)


@pytest.mark.parametrize(
    ("disposition", "permits_no_exit"),
    [(_CONTINUE, False), (_FINISH_WITHOUT_STAMP, True)],
)
def test_permits_no_exit_matches_the_table(
    disposition: RunningStepDisposition,
    permits_no_exit: bool,
) -> None:
    assert disposition.permits_no_exit is permits_no_exit
    assert permits_no_exit is not any(
        disposition.permits(step_exit, is_needed=lambda: True) for step_exit in StepExit
    )


def test_the_lattice_orders_continue_below_finish_without_stamp() -> None:
    assert _CONTINUE < _FINISH_WITHOUT_STAMP
    assert max(_FINISH_WITHOUT_STAMP, _CONTINUE) is _FINISH_WITHOUT_STAMP
