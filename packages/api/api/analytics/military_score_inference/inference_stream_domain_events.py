"""Domain-level events emitted by the inference row scheduler."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.host_turn_targets import HostTurnFunctionalTarget
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceResult,
    InferenceSolution,
)


@dataclass(frozen=True)
class HeldSolutionsUpdated:
    solutions: tuple[InferenceSolution, ...] | list[InferenceSolution]
    catalog: ActionCatalog
    observation: InferenceObservation | None = None
    segment_id: str | None = None


@dataclass(frozen=True)
class TierProgress:
    policy_step_id: str | None = None
    combo_count: int | None = None
    held_count: int | None = None


@dataclass(frozen=True)
class RowCompleteWirePayload:
    status: str
    summary: str
    solution_count: int
    is_complete: bool
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None = None
    host_turn_targets: list[HostTurnFunctionalTarget] | None = None


@dataclass(frozen=True)
class RowComplete:
    result: InferenceResult
    wire_payload: RowCompleteWirePayload


@dataclass(frozen=True)
class RowFailed:
    detail: str


@dataclass(frozen=True)
class GlobalPauseChanged:
    paused: bool


InferenceStreamDomainEvent = (
    HeldSolutionsUpdated | TierProgress | RowComplete | RowFailed | GlobalPauseChanged
)
