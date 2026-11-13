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
    assert disposition.permits(step_exit, is_needed=is_needed) is permitted


def test_every_disposition_answers_every_exit() -> None:
    for disposition in RunningStepDisposition:
        for step_exit in StepExit:
            disposition.permits(step_exit, is_needed=False)


def test_the_lattice_orders_continue_below_finish_without_stamp() -> None:
    assert _CONTINUE < _FINISH_WITHOUT_STAMP
    assert max(_FINISH_WITHOUT_STAMP, _CONTINUE) is _FINISH_WITHOUT_STAMP
