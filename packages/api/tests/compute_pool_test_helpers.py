"""Module-level helpers for compute pool integration tests (shareable run_step)."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from api.compute.pools import RemoteStepWork, ThreadStepWork
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import BuildStepJobWireKwargs, DependencyOutputs

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


def run_interpreter_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}


def run_process_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}


def _never_run(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("this test's pool work must not run")


# Pool work for a test item that is queued, inspected or picked, but never run.
QUEUED_ONLY_STEP_WORK = RemoteStepWork(job_wire=None, run_step=_never_run)


def unbuilt_thread_step_work(ctx: AnalyticQueryContext) -> ThreadStepWork:
    """Thread-step work for an item run by a stub orchestrator that never builds its wire."""
    return ThreadStepWork(
        build_job_wire=_never_run,
        job_wire_kwargs=BuildStepJobWireKwargs(
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
            node_result_wire=None,
            submission_open=SubmissionOpen(),
            execution_generation=0,
        ),
        run_step=_never_run,
    )
