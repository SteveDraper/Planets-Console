"""Module-level helpers for compute pool integration tests (shareable run_step)."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from api.compute.pools import RemoteStepWork, ThreadStepWork
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import BuildStepJobWireKwargs, DependencyOutputs

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.orchestrator import ComputeOrchestrator
    from api.compute.scope import ComputeScope


def run_interpreter_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}


def run_process_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}


def _never_run(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("this test's pool work must not run")


# Pool work for a test item that is queued, inspected or picked, but never run.
QUEUED_ONLY_STEP_WORK = RemoteStepWork(backend="process", job_wire=None, run_step=_never_run)


def ok_thread_step_work(ctx: AnalyticQueryContext) -> ThreadStepWork:
    """Thread-step work that builds an empty job wire and returns ``{"ok": True}``."""
    return ThreadStepWork(
        build_job_wire=lambda _scope, **_kwargs: {},
        job_wire_kwargs=BuildStepJobWireKwargs(
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
            node_result_wire=None,
            submission_open=SubmissionOpen(),
            execution_generation=0,
        ),
        run_step=lambda _job: {"ok": True},
    )


def complete_running_pool_step(
    orchestrator: ComputeOrchestrator,
    scope: ComputeScope,
    *,
    result_wire: object | None = None,
    error: BaseException | None = None,
    step_kind: str | None = None,
    step_index: int | None = None,
) -> None:
    """Finish ``scope``'s pool step as the item its current execution dispatched."""
    orchestrator.complete_pool_step(
        scope,
        orchestrator.nodes[scope].execution_generation,
        result_wire=result_wire,
        error=error,
        step_kind=step_kind,
        step_index=step_index,
    )
