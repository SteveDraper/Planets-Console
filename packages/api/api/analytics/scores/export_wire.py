"""Wire shaping helpers for scores export solution payloads."""

from __future__ import annotations

from typing import Literal

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import build_inference_solver_diagnostics
from api.analytics.military_score_inference.inference_api_payload import (
    FUNCTIONAL_LEFTOVER_STATUSES,
    INFERENCE_ADMISSION_SKIP_STATUSES,
    serialize_solution_without_arithmetic,
    serialize_solutions_with_arithmetic,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.transport.inference_stream import inference_complete_functional_fields

TerminalWireSearchStatus = Literal["complete", "stopped"]


def is_terminal_wire_complete_semantics(*, is_complete: bool, status: str) -> bool:
    """Return whether wire/API fields describe a terminal inference outcome."""
    if is_complete:
        return True
    return status == STATUS_STOPPED


def is_terminal_wire_complete_event(wire_event: dict[str, object]) -> bool:
    """Return whether a wire ``complete`` event is terminal."""
    return is_terminal_wire_complete_semantics(
        is_complete=bool(wire_event.get("isComplete")),
        status=str(wire_event.get("status", "")),
    )


def is_terminal_inference_api_payload(payload: dict[str, object]) -> bool:
    """Return whether a scores row inference API payload is terminal."""
    return is_terminal_wire_complete_semantics(
        is_complete=bool(payload.get("isComplete")),
        status=str(payload.get("status", "")),
    )


def search_status_from_wire_complete_event(
    wire_event: dict[str, object],
) -> TerminalWireSearchStatus:
    """Derive lifecycle status from a terminal wire ``complete`` event."""
    if str(wire_event.get("status", "")) == STATUS_STOPPED:
        return "stopped"
    return "complete"


def ranked_solutions_from_wire(
    wire_solutions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return held solutions in rank order, matching inference row wire shape."""
    return sorted(
        wire_solutions,
        key=lambda solution: int(solution.get("objectiveValue", 0)),
        reverse=True,
    )


def solutions_diagnostics_from_wire_complete_event(
    wire_event: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    """Extract solutions, diagnostics, and held count from a wire complete event."""
    wire_solutions = wire_event.get("solutions")
    solutions = ranked_solutions_from_wire(
        wire_solutions if isinstance(wire_solutions, list) else []
    )
    event_diagnostics = wire_event.get("diagnostics")
    diagnostics = event_diagnostics if isinstance(event_diagnostics, dict) else None
    solutions_held = int(wire_event.get("solutionCount", 0))
    return solutions, diagnostics, solutions_held


def solutions_from_domain(
    solutions: list[InferenceSolution] | tuple[InferenceSolution, ...],
    *,
    observation: InferenceObservation | None = None,
    catalog: ActionCatalog | None = None,
) -> list[dict[str, object]]:
    """Serialize held domain solutions using the same shape as inference row wire."""
    ranked = sorted(solutions, key=lambda solution: solution.objective_value, reverse=True)
    if observation is not None and catalog is not None:
        return serialize_solutions_with_arithmetic(observation, catalog, ranked)
    return [serialize_solution_without_arithmetic(solution) for solution in ranked]


def wire_complete_event_from_terminal_admission(
    admission: ImmediateRowAdmission | CachedCompleteRowAdmission,
) -> dict[str, object]:
    """Return the terminal wire ``complete`` event carried by row admission."""
    if isinstance(admission, ImmediateRowAdmission):
        return admission.events[-1]
    if admission.event is None:
        raise ValueError("CachedCompleteRowAdmission must carry a terminal wire-complete event")
    return admission.event


def terminal_row_admission(
    admission: RowStreamAdmission | None,
) -> ImmediateRowAdmission | CachedCompleteRowAdmission | None:
    """Return admission only when it carries a terminal wire-complete payload."""
    if isinstance(admission, ImmediateRowAdmission) and admission.events:
        return admission
    if isinstance(admission, CachedCompleteRowAdmission) and admission.event is not None:
        return admission
    return None


def normalize_export_product_fields(
    status: str | None,
    placeholders: list[dict[str, object]] | None,
    leftover: int | None,
) -> tuple[str | None, list[dict[str, object]] | None, int | None]:
    """Normalize product ``status``, leftover, and ``placeholders`` for the export tree.

    Residual / ``no_exact_solution`` always expose leftover and ``placeholders``
    (empty arrays are authoritative until placeholders are populated). Skip
    rows expose empty ``placeholders`` and omit leftover. Other statuses omit
    both branches unless the source already carried them.
    """
    if status is None:
        return None, None, None
    resolved_placeholders = placeholders
    if (
        status in FUNCTIONAL_LEFTOVER_STATUSES or status in INFERENCE_ADMISSION_SKIP_STATUSES
    ) and resolved_placeholders is None:
        resolved_placeholders = []
    resolved_leftover = leftover if status in FUNCTIONAL_LEFTOVER_STATUSES else None
    return status, resolved_placeholders, resolved_leftover


def product_fields_from_wire_complete(
    wire_event: dict[str, object],
) -> tuple[str | None, list[dict[str, object]] | None, int | None]:
    """Extract product status, placeholders, and leftover from a wire complete event."""
    raw_status = wire_event.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status else None
    placeholders, leftover = inference_complete_functional_fields(wire_event)
    return normalize_export_product_fields(status, placeholders, leftover)


def product_fields_from_persisted_row(
    persisted_row: PersistedInferenceRow,
) -> tuple[str | None, list[dict[str, object]] | None, int | None]:
    """Extract product status, placeholders, and leftover from a persisted inference row."""
    return normalize_export_product_fields(
        persisted_row.status,
        persisted_row.placeholders,
        persisted_row.unexplained_military_delta_2x,
    )


def solutions_from_persisted_row(
    persisted_row: PersistedInferenceRow,
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    return (
        ranked_solutions_from_wire(persisted_row.solutions),
        persisted_row.diagnostics,
        persisted_row.solution_count,
    )


def _diagnostics_from_scheduler_ladder(scheduler_run: RowRun) -> dict[str, object] | None:
    """Build scores row inference diagnostics wire from live scheduler ladder state."""
    ladder_state = scheduler_run.ladder_state
    if ladder_state is None:
        raise ValueError("scheduler run must have ladder_state for diagnostics")
    if (
        not ladder_state.last_diagnostics
        and ladder_state.catalog is None
        and not ladder_state.step_diagnostics
        and not ladder_state.policy_steps_attempted
    ):
        return None

    session = scheduler_run.session
    solver_diagnostics: dict[str, object] = {
        "status": ladder_state.last_status,
        **ladder_state.last_diagnostics,
    }
    extra: dict[str, object] = {
        "solution_count": len(ladder_state.merged_solutions),
    }
    if ladder_state.policy_steps_attempted:
        extra["policy_steps_attempted"] = list(ladder_state.policy_steps_attempted)
    if ladder_state.step_diagnostics:
        extra["policy_step_attempts"] = list(ladder_state.step_diagnostics)

    return build_inference_solver_diagnostics(
        turn=session.turn.settings.turn,
        observation=session.observation,
        problem=ladder_state.problem,
        catalog=ladder_state.catalog,
        turn_info=session.turn,
        solver=solver_diagnostics,
        extra=extra,
    )


def solutions_from_terminal_admission(
    admission: ImmediateRowAdmission | CachedCompleteRowAdmission,
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    """Serialize solutions from one terminal wire-complete row admission."""
    if isinstance(admission, ImmediateRowAdmission):
        return solutions_diagnostics_from_wire_complete_event(admission.events[-1])
    if admission.event is None:
        raise ValueError("CachedCompleteRowAdmission must carry a terminal wire-complete event")
    return solutions_diagnostics_from_wire_complete_event(admission.event)


def solutions_from_scheduler_run(
    scheduler_run: RowRun,
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    """Serialize solutions from live scheduler ladder state when present."""
    ladder_state = scheduler_run.ladder_state
    if ladder_state is None:
        return [], None, 0
    merged = ladder_state.merged_solutions
    return (
        solutions_from_domain(
            merged,
            observation=scheduler_run.session.observation,
            catalog=ladder_state.catalog,
        ),
        _diagnostics_from_scheduler_ladder(scheduler_run),
        len(merged),
    )
