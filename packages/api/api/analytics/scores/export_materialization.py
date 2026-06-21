"""Shared materialization helpers for scores analytic exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    _serialize_solution_without_arithmetic,
    serialize_solutions_with_arithmetic,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
)
from api.serialization.inference_row_persistence import PersistedInferenceRow

SearchStatus = Literal["not_started", "in_progress", "paused", "stopped", "complete"]


@dataclass(frozen=True)
class ScoresInferenceSnapshot:
    """Gathered inference state for scores export persistence and materialization."""

    persisted_row: PersistedInferenceRow | None
    admission: RowStreamAdmission | None
    scheduler_run: RowRun | None
    globally_paused: bool
    scope_matches_active_stream: bool


@dataclass(frozen=True)
class ScoresExportPayload:
    """Resolved export status and solution payload for a scores inference snapshot."""

    search_status: SearchStatus
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None
    solutions_held: int


_PERSISTABLE_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})
_IMMEDIATE_COMPLETE_STATUSES = frozenset(
    {
        STATUS_NO_PRIOR_TURN,
        "player_not_found",
        STATUS_EXACT,
        STATUS_NO_EXACT_SOLUTION,
        "invalid_problem",
        "solver_error",
    }
)


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
    return [_serialize_solution_without_arithmetic(solution) for solution in ranked]


def export_meta_branch(
    *,
    search_status: SearchStatus,
    host_turn: int,
    solutions_held: int = 0,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "searchStatus": search_status,
        "hostTurn": host_turn,
    }
    if solutions_held > 0:
        meta["solutionsHeld"] = solutions_held
    return meta


def hull_catalog_mask_branch(enabled_hull_ids: frozenset[int] | set[int]) -> dict[str, object]:
    return {"enabledHullIds": sorted(enabled_hull_ids)}


def _payload_from_persisted_row(
    search_status: SearchStatus,
    persisted_row: PersistedInferenceRow,
) -> ScoresExportPayload:
    return ScoresExportPayload(
        search_status=search_status,
        solutions=ranked_solutions_from_wire(persisted_row.solutions),
        diagnostics=persisted_row.diagnostics,
        solutions_held=persisted_row.solution_count,
    )


def _search_status_from_scheduler(
    scheduler_run: RowRun,
    *,
    globally_paused: bool,
    scope_matches_active_stream: bool,
) -> SearchStatus:
    if globally_paused and scope_matches_active_stream:
        return "paused"
    ladder_state = scheduler_run.ladder_state
    if ladder_state is not None and ladder_state.last_status == STATUS_STOPPED:
        return "stopped"
    if (
        ladder_state is not None
        and ladder_state.time_limited
        and not ladder_state.ladder_complete
    ):
        return "in_progress"
    return "in_progress"


def _solutions_from_scheduler_ladder(
    scheduler_run: RowRun,
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    ladder_state = scheduler_run.ladder_state
    assert ladder_state is not None
    merged = ladder_state.merged_solutions
    return (
        solutions_from_domain(
            merged,
            observation=scheduler_run.session.observation,
            catalog=ladder_state.catalog,
        ),
        None,
        len(merged),
    )


def _solutions_from_admission_or_scheduler(
    *,
    admission: RowStreamAdmission | None,
    scheduler_run: RowRun | None,
    persisted_row: PersistedInferenceRow | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None, int]:
    if isinstance(admission, ImmediateRowAdmission) and admission.events:
        return solutions_diagnostics_from_wire_complete_event(admission.events[-1])
    if (
        isinstance(admission, CachedCompleteRowAdmission)
        and admission.event is not None
    ):
        return solutions_diagnostics_from_wire_complete_event(admission.event)
    if scheduler_run is not None and scheduler_run.ladder_state is not None:
        return _solutions_from_scheduler_ladder(scheduler_run)
    return (
        [],
        None,
        held_solution_count(
            persisted_row=persisted_row,
            scheduler_run=scheduler_run,
        ),
    )


def resolve_scores_export_payload(snapshot: ScoresInferenceSnapshot) -> ScoresExportPayload:
    """Resolve search status and solution sources from one precedence ladder."""
    persisted_row = snapshot.persisted_row
    admission = snapshot.admission
    scheduler_run = snapshot.scheduler_run

    if persisted_row is not None and persisted_row.status in _PERSISTABLE_STATUSES:
        return _payload_from_persisted_row("complete", persisted_row)

    if persisted_row is not None and persisted_row.status == STATUS_STOPPED:
        return _payload_from_persisted_row("stopped", persisted_row)

    if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission)):
        solutions, diagnostics, solutions_held = _solutions_from_admission_or_scheduler(
            admission=admission,
            scheduler_run=scheduler_run,
            persisted_row=persisted_row,
        )
        return ScoresExportPayload(
            search_status="complete",
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    if scheduler_run is not None:
        solutions, diagnostics, solutions_held = _solutions_from_admission_or_scheduler(
            admission=None,
            scheduler_run=scheduler_run,
            persisted_row=persisted_row,
        )
        return ScoresExportPayload(
            search_status=_search_status_from_scheduler(
                scheduler_run,
                globally_paused=snapshot.globally_paused,
                scope_matches_active_stream=snapshot.scope_matches_active_stream,
            ),
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    if persisted_row is not None and persisted_row.status in _IMMEDIATE_COMPLETE_STATUSES:
        return _payload_from_persisted_row("complete", persisted_row)

    if persisted_row is not None:
        return _payload_from_persisted_row("not_started", persisted_row)

    return ScoresExportPayload(
        search_status="not_started",
        solutions=[],
        diagnostics=None,
        solutions_held=held_solution_count(
            persisted_row=persisted_row,
            scheduler_run=scheduler_run,
        ),
    )


def resolve_search_status(
    *,
    persisted_row,
    admission: RowStreamAdmission | None,
    scheduler_run: RowRun | None,
    globally_paused: bool,
    scope_matches_active_stream: bool,
) -> SearchStatus:
    return resolve_scores_export_payload(
        ScoresInferenceSnapshot(
            persisted_row=persisted_row,
            admission=admission,
            scheduler_run=scheduler_run,
            globally_paused=globally_paused,
            scope_matches_active_stream=scope_matches_active_stream,
        )
    ).search_status


def held_solution_count(
    *,
    persisted_row,
    scheduler_run: RowRun | None,
) -> int:
    if persisted_row is not None:
        return persisted_row.solution_count
    if scheduler_run is not None and scheduler_run.ladder_state is not None:
        return len(scheduler_run.ladder_state.merged_solutions)
    return 0


def is_persistable_inference_status(status: str) -> bool:
    return status in _PERSISTABLE_STATUSES


def is_scores_export_inference_satisfied(
    *,
    persisted_row,
    admission: RowStreamAdmission | None,
    scheduler_run: RowRun | None,
    globally_paused: bool,
    scope_matches_active_stream: bool,
) -> bool:
    """True when inference is terminal and satisfied for export dependency probes."""
    return (
        resolve_scores_export_payload(
            ScoresInferenceSnapshot(
                persisted_row=persisted_row,
                admission=admission,
                scheduler_run=scheduler_run,
                globally_paused=globally_paused,
                scope_matches_active_stream=scope_matches_active_stream,
            )
        ).search_status
        == "complete"
    )
