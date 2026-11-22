"""Serializable job and result wire types for compute leaf steps."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypedDict, Unpack

from api.analytics.exports.jsonpath import resolve_jsonpath
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

StepOutcome = Literal["continue", "persist", "complete", "park"]

# Compute plane: job payload -> serializable result payload.
RunStepFn = Callable[[Any], Any]


@dataclass(frozen=True)
class StepResult:
    """Explicit orchestrator step outcome with an optional serializable payload."""

    outcome: StepOutcome
    payload: object | None = None
    park_reason: str | None = None
    # When true, ``persist`` runs but the node advances to the next profile step.
    persist_then_continue: bool = False


class MalformedStepResultError(ValueError):
    """A step returned a result wire that does not name a valid step outcome.

    The orchestrator fails the step's node with it, as it fails a step that raises.
    """


def coerce_step_result(result_wire: object) -> StepResult:
    """Normalize a leaf step return value into an explicit step outcome.

    Raises :class:`MalformedStepResultError` when an outcome-tagged wire is invalid.
    """
    if isinstance(result_wire, StepResult):
        return result_wire
    if isinstance(result_wire, dict) and "outcome" in result_wire:
        outcome = result_wire["outcome"]
        if outcome not in {"continue", "persist", "complete", "park"}:
            raise MalformedStepResultError(f"invalid step outcome {outcome!r}")
        park_reason = result_wire.get("parkReason")
        if park_reason is not None and not isinstance(park_reason, str):
            raise MalformedStepResultError("parkReason must be a string when provided")
        persist_then_continue = bool(result_wire.get("persistThenContinue", False))
        return StepResult(
            outcome=outcome,
            payload=result_wire.get("payload"),
            park_reason=park_reason,
            persist_then_continue=persist_then_continue,
        )
    return StepResult(outcome="persist", payload=result_wire)


@dataclass
class DependencyOutputs:
    """Ancestor result wires for job-wire builders."""

    _by_scope: dict[ComputeScope, object] = field(default_factory=dict)

    def put(self, scope: ComputeScope, result_wire: object) -> None:
        self._by_scope[scope] = result_wire

    def get(self, scope: ComputeScope) -> object | None:
        return self._by_scope.get(scope)

    def require(
        self,
        *,
        analytic_id: str,
        scope: ComputeScope,
        paths: tuple[str, ...],
    ) -> dict[str, list[Any]]:
        if scope not in self._by_scope:
            raise KeyError(f"dependency output missing for scope {scope!r}")
        if scope.analytic_id != analytic_id:
            raise ValueError(
                f"dependency scope analytic_id {scope.analytic_id!r} "
                f"does not match required {analytic_id!r}"
            )
        result_wire = self._by_scope[scope]
        return {path: resolve_jsonpath(result_wire, path) for path in paths}

    def as_mapping(self) -> Mapping[ComputeScope, object]:
        return self._by_scope


class BuildStepJobWireKwargs(TypedDict):
    """Keyword arguments passed to job-wire builders by the orchestrator.

    The orchestrator snapshots every field under its lock in one helper, so a
    new builder input is added here and there only.
    """

    dependency_outputs: DependencyOutputs
    ctx: AnalyticQueryContext
    node_result_wire: object | None
    # Root turn and backfill choice of the submission that owns this node.
    submission_open: SubmissionOpen
    # Identity of the node execution the wire is built for. A replaced node
    # gets a new one; requeues of the same node keep it.
    execution_generation: int
    # Whether that execution is still live. It reads the node without the
    # orchestrator lock, so a builder may ask under its own locks. False is
    # final: a node's generation never changes and a terminal node stays terminal.
    is_execution_live: Callable[[], bool]


# Orchestration plane: scope + dependency outputs -> serializable job payload.
BuildStepJobWireFn = Callable[
    [ComputeScope, Unpack[BuildStepJobWireKwargs]],
    Any,
]
