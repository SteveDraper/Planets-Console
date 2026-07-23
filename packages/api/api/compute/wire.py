"""Serializable job and result wire types for compute leaf steps."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypedDict, Unpack

from api.analytics.exports.jsonpath import resolve_jsonpath
from api.compute.persistence import PersistDependencyRecovery
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

StepOutcome = Literal["continue", "persist", "complete", "park", "waiting_deps"]

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
    # Optional cross-scope recovery (graft + optional force_fresh). Soft defer
    # omits this so demotion does not self-graft the waiting node.
    wait_recovery: PersistDependencyRecovery | None = None


def coerce_step_result(result_wire: object) -> StepResult:
    """Normalize a leaf step return value into an explicit step outcome."""
    if isinstance(result_wire, StepResult):
        return result_wire
    if isinstance(result_wire, dict) and "outcome" in result_wire:
        outcome = result_wire["outcome"]
        if outcome not in {"continue", "persist", "complete", "park", "waiting_deps"}:
            raise ValueError(f"invalid step outcome {outcome!r}")
        park_reason = result_wire.get("parkReason")
        if park_reason is not None and not isinstance(park_reason, str):
            raise ValueError("parkReason must be a string when provided")
        persist_then_continue = bool(result_wire.get("persistThenContinue", False))
        wait_recovery = result_wire.get("waitRecovery")
        if wait_recovery is not None and not isinstance(wait_recovery, PersistDependencyRecovery):
            raise ValueError("waitRecovery must be PersistDependencyRecovery when provided")
        return StepResult(
            outcome=outcome,
            payload=result_wire.get("payload"),
            park_reason=park_reason,
            persist_then_continue=persist_then_continue,
            wait_recovery=wait_recovery,
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


class BuildStepJobWireKwargs(TypedDict, total=False):
    """Keyword arguments passed to job-wire builders by the orchestrator."""

    dependency_outputs: DependencyOutputs
    ctx: AnalyticQueryContext | None
    node_result_wire: object | None


# Orchestration plane: scope + dependency outputs -> serializable job payload.
BuildStepJobWireFn = Callable[
    [ComputeScope, Unpack[BuildStepJobWireKwargs]],
    Any,
]
