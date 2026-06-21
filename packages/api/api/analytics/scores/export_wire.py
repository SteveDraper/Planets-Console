"""Wire shaping helpers for scores export solution payloads."""

from __future__ import annotations

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_api_payload import (
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
from api.serialization.inference_row_persistence import PersistedInferenceRow


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


def terminal_row_admission(
    admission: RowStreamAdmission | None,
) -> ImmediateRowAdmission | CachedCompleteRowAdmission | None:
    """Return admission only when it carries a terminal wire-complete payload."""
    if isinstance(admission, ImmediateRowAdmission) and admission.events:
        return admission
    if isinstance(admission, CachedCompleteRowAdmission) and admission.event is not None:
        return admission
    return None


def held_solution_count(
    *,
    persisted_row: PersistedInferenceRow | None,
    scheduler_run: RowRun | None,
) -> int:
    if persisted_row is not None:
        return persisted_row.solution_count
    if scheduler_run is not None and scheduler_run.ladder_state is not None:
        return len(scheduler_run.ladder_state.merged_solutions)
    return 0


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
    assert ladder_state is not None
    if (
        not ladder_state.last_diagnostics
        and ladder_state.catalog is None
        and not ladder_state.step_diagnostics
        and not ladder_state.policy_steps_attempted
    ):
        return None

    from api.analytics.military_score_inference.analytic import build_inference_solver_diagnostics

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
    assert admission.event is not None
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
