"""Domain-level events emitted by the inference row scheduler."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)


@dataclass(frozen=True)
class HeldSolutionsUpdated:
    solutions: tuple[InferenceSolution, ...] | list[InferenceSolution]
    catalog: ActionCatalog


@dataclass(frozen=True)
class TierProgress:
    policy_step_id: str | None = None
    combo_count: int | None = None
    held_count: int | None = None


@dataclass(frozen=True)
class RowComplete:
    result: InferenceResult
    catalog: ActionCatalog | None = None
    problem: InferenceProblem | None = None
    policy_steps_attempted: list[str] | None = None
    step_diagnostics: list[dict[str, object]] | None = None
    force_is_complete: bool | None = None
    summary_override: str | None = None


@dataclass(frozen=True)
class RowApiPayloadReady:
    """API-shaped row result from analytic; converted to NDJSON at the stream boundary."""

    payload: dict[str, object]
    emit_solution_event: bool = True


@dataclass(frozen=True)
class RowFailed:
    detail: str


@dataclass(frozen=True)
class GlobalPauseChanged:
    paused: bool


InferenceStreamDomainEvent = (
    HeldSolutionsUpdated
    | TierProgress
    | RowComplete
    | RowApiPayloadReady
    | RowFailed
    | GlobalPauseChanged
)
