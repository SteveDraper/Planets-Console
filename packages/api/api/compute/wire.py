"""Serializable job and result wire types for compute leaf steps."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from api.compute.scope import ComputeScope

# Orchestration plane: scope + dependency outputs -> serializable job payload.
BuildStepJobWireFn = Callable[..., Any]

# Compute plane: job payload -> serializable result payload.
RunStepFn = Callable[[Any], Any]


@dataclass
class DependencyOutputs:
    """Ancestor result wires for job-wire builders.

    Full path projection arrives in #198; this slice stores whole result wires
    keyed by completed dependency scope.
    """

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
    ) -> object:
        del analytic_id, paths
        if scope not in self._by_scope:
            raise KeyError(f"dependency output missing for scope {scope!r}")
        return self._by_scope[scope]

    def as_mapping(self) -> Mapping[ComputeScope, object]:
        return self._by_scope
