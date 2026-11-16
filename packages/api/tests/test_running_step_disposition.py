"""The running-step lattice and what each disposition permits."""

from __future__ import annotations

import pytest
from api.compute.running_step import RunningStepDisposition, StepExit

_CONTINUE = RunningStepDisposition.CONTINUE
_END_AFTER_STEP = RunningStepDisposition.END_AFTER_STEP


@pytest.mark.parametrize(
    ("disposition", "step_exit", "permitted"),
    [
        (_CONTINUE, StepExit.PERSIST, True),
        (_CONTINUE, StepExit.COMPLETE, True),
        (_CONTINUE, StepExit.START, True),
        (_CONTINUE, StepExit.REQUEUE, True),
        (_END_AFTER_STEP, StepExit.PERSIST, True),
        (_END_AFTER_STEP, StepExit.COMPLETE, True),
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


@pytest.mark.parametrize("step_exit", [StepExit.START, StepExit.REQUEUE])
@pytest.mark.parametrize("is_needed", [True, False])
def test_end_after_step_starts_or_requeues_only_while_needed(
    step_exit: StepExit,
    is_needed: bool,
) -> None:
    assert _END_AFTER_STEP.permits(step_exit, is_needed=lambda: is_needed) is is_needed


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


def test_the_lattice_orders_continue_below_end_after_step() -> None:
    assert _CONTINUE < _END_AFTER_STEP
    assert max(_END_AFTER_STEP, _CONTINUE) is _END_AFTER_STEP
    assert list(RunningStepDisposition) == [_CONTINUE, _END_AFTER_STEP]
