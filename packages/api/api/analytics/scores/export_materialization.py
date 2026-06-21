"""Shared materialization helpers for scores analytic exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_SOLVER_ERROR,
    serialize_solution_without_arithmetic,
    serialize_solutions_with_arithmetic,
)
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.export_services import ResolvedScoresServices
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
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


@dataclass(frozen=True)
class ScoresExportPayload:
    """Resolved export status and solution payload for a scores inference snapshot."""

    search_status: SearchStatus
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None
    solutions_held: int


_PERSISTABLE_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})
_FALLBACK_COMPLETE_PERSISTED_STATUSES = frozenset(
    {
        STATUS_NO_PRIOR_TURN,
        STATUS_PLAYER_NOT_FOUND,
        STATUS_INVALID_PROBLEM,
        STATUS_SOLVER_ERROR,
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
    return [serialize_solution_without_arithmetic(solution) for solution in ranked]


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


def _persisted_row_priority_search_status(status: str) -> SearchStatus | None:
    """Persisted statuses that override live admission or scheduler state."""
    if status in _PERSISTABLE_STATUSES:
        return "complete"
    if status == STATUS_STOPPED:
        return "stopped"
    return None


def _persisted_row_fallback_search_status(status: str) -> SearchStatus:
    """Persisted statuses used when admission and scheduler are absent."""
    if status in _FALLBACK_COMPLETE_PERSISTED_STATUSES:
        return "complete"
    return "not_started"


def _search_status_from_scheduler(
    scheduler_run: RowRun,
    *,
    globally_paused: bool,
) -> SearchStatus:
    if globally_paused:
        return "paused"
    ladder_state = scheduler_run.ladder_state
    # enqueue_tier_ladder has not run yet; the row is still scheduled.
    if ladder_state is None:
        return "in_progress"
    if ladder_state.last_status == STATUS_STOPPED:
        return "stopped"
    if ladder_state.time_limited:
        return "stopped"
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
    if isinstance(admission, CachedCompleteRowAdmission) and admission.event is not None:
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

    if persisted_row is not None:
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        if priority_status is not None:
            return _payload_from_persisted_row(priority_status, persisted_row)

    if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission)) or scheduler_run is not None:
        search_status = (
            "complete"
            if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission))
            else _search_status_from_scheduler(
                scheduler_run,
                globally_paused=snapshot.globally_paused,
            )
        )
        solutions, diagnostics, solutions_held = _solutions_from_admission_or_scheduler(
            admission=admission
            if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission))
            else None,
            scheduler_run=scheduler_run,
            persisted_row=persisted_row,
        )
        return ScoresExportPayload(
            search_status=search_status,
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    if persisted_row is not None:
        return _payload_from_persisted_row(
            _persisted_row_fallback_search_status(persisted_row.status),
            persisted_row,
        )

    return ScoresExportPayload(
        search_status="not_started",
        solutions=[],
        diagnostics=None,
        solutions_held=held_solution_count(
            persisted_row=persisted_row,
            scheduler_run=scheduler_run,
        ),
    )


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


def is_persistable_inference_status(status: str) -> bool:
    return status in _PERSISTABLE_STATUSES


def scores_inference_stream_scope(scope: ExportScope) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
    )


def _load_persisted_row(
    services: ResolvedScoresServices,
    scope: ExportScope,
) -> PersistedInferenceRow | None:
    if services.persistence is None or scope.player_id is None:
        return None
    return services.persistence.get_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )


def _row_admission(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
):
    if scope.player_id is None:
        return None
    return resolve_row_stream_admission(
        turn,
        scope.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
        load_scoreboard_turn=ctx.load_turn,
        persistence=services.persistence,
    )


def _scheduler_row_run(services: ResolvedScoresServices, scope: ExportScope):
    if scope.player_id is None:
        return None
    stream_scope = scores_inference_stream_scope(scope)
    return services.scheduler.row_run_for_player(stream_scope, scope.player_id)


def gather_scores_inference_snapshot(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> ScoresInferenceSnapshot:
    persisted_row = _load_persisted_row(services, scope)
    if turn is None:
        return ScoresInferenceSnapshot(
            persisted_row=persisted_row,
            admission=None,
            scheduler_run=None,
            globally_paused=False,
        )

    stream_scope = scores_inference_stream_scope(scope)
    pause_status = services.scheduler.global_pause_status(stream_scope)
    return ScoresInferenceSnapshot(
        persisted_row=persisted_row,
        admission=_row_admission(ctx, services, scope, turn),
        scheduler_run=_scheduler_row_run(services, scope),
        globally_paused=bool(pause_status.get("paused")),
    )
