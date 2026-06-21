"""Export precedence classification and payload resolution for scores inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_SOLVER_ERROR,
)
from api.analytics.military_score_inference.inference_stream_rows import RowStreamAdmission
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
)
from api.serialization.inference_row_persistence import PersistedInferenceRow

SearchStatus = Literal["not_started", "in_progress", "paused", "stopped", "complete"]
ScoresExportPrecedenceBranch = Literal[
    "priority_persisted",
    "terminal_admission",
    "scheduler",
    "fallback_persisted",
    "empty",
]

PERSISTABLE_INFERENCE_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})
_FALLBACK_COMPLETE_PERSISTED_STATUSES = frozenset(
    {
        STATUS_NO_PRIOR_TURN,
        STATUS_PLAYER_NOT_FOUND,
        STATUS_INVALID_PROBLEM,
        STATUS_SOLVER_ERROR,
    }
)


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


def _persisted_row_priority_search_status(status: str) -> SearchStatus | None:
    """Persisted statuses that override live admission or scheduler state."""
    if status in PERSISTABLE_INFERENCE_STATUSES:
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


@dataclass(frozen=True)
class _ScoresExportResolution:
    branch: ScoresExportPrecedenceBranch
    search_status: SearchStatus
    solutions: list[dict[str, object]] | None = None
    diagnostics: dict[str, object] | None = None
    solutions_held: int | None = None

    def as_payload(self) -> ScoresExportPayload:
        assert self.solutions is not None
        assert self.solutions_held is not None
        return ScoresExportPayload(
            search_status=self.search_status,
            solutions=self.solutions,
            diagnostics=self.diagnostics,
            solutions_held=self.solutions_held,
        )


def _payload_from_persisted_row(
    search_status: SearchStatus,
    persisted_row: PersistedInferenceRow,
) -> ScoresExportPayload:
    from api.analytics.scores.export_materialization import ranked_solutions_from_wire

    return ScoresExportPayload(
        search_status=search_status,
        solutions=ranked_solutions_from_wire(persisted_row.solutions),
        diagnostics=persisted_row.diagnostics,
        solutions_held=persisted_row.solution_count,
    )


def _resolve_scores_export(
    snapshot: ScoresInferenceSnapshot,
    *,
    materialize_payload: bool,
) -> _ScoresExportResolution:
    """Classify precedence and resolve status, optionally materializing solutions."""
    from api.analytics.scores.export_materialization import (
        _solutions_from_admission_or_scheduler,
        held_solution_count,
        terminal_row_admission,
    )

    persisted_row = snapshot.persisted_row
    admission = snapshot.admission
    scheduler_run = snapshot.scheduler_run

    if persisted_row is not None:
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        if priority_status is not None:
            if materialize_payload:
                payload = _payload_from_persisted_row(priority_status, persisted_row)
                return _ScoresExportResolution(
                    branch="priority_persisted",
                    search_status=priority_status,
                    solutions=payload.solutions,
                    diagnostics=payload.diagnostics,
                    solutions_held=payload.solutions_held,
                )
            return _ScoresExportResolution(
                branch="priority_persisted",
                search_status=priority_status,
            )

    if terminal_row_admission(admission) is not None:
        if materialize_payload:
            solutions, diagnostics, solutions_held = _solutions_from_admission_or_scheduler(
                admission=admission,
                scheduler_run=scheduler_run,
                persisted_row=persisted_row,
            )
            return _ScoresExportResolution(
                branch="terminal_admission",
                search_status="complete",
                solutions=solutions,
                diagnostics=diagnostics,
                solutions_held=solutions_held,
            )
        return _ScoresExportResolution(
            branch="terminal_admission",
            search_status="complete",
        )

    if scheduler_run is not None:
        search_status = _search_status_from_scheduler(
            scheduler_run,
            globally_paused=snapshot.globally_paused,
        )
        if materialize_payload:
            solutions, diagnostics, solutions_held = _solutions_from_admission_or_scheduler(
                admission=None,
                scheduler_run=scheduler_run,
                persisted_row=persisted_row,
            )
            return _ScoresExportResolution(
                branch="scheduler",
                search_status=search_status,
                solutions=solutions,
                diagnostics=diagnostics,
                solutions_held=solutions_held,
            )
        return _ScoresExportResolution(
            branch="scheduler",
            search_status=search_status,
        )

    if persisted_row is not None:
        fallback_status = _persisted_row_fallback_search_status(persisted_row.status)
        if materialize_payload:
            payload = _payload_from_persisted_row(fallback_status, persisted_row)
            return _ScoresExportResolution(
                branch="fallback_persisted",
                search_status=fallback_status,
                solutions=payload.solutions,
                diagnostics=payload.diagnostics,
                solutions_held=payload.solutions_held,
            )
        return _ScoresExportResolution(
            branch="fallback_persisted",
            search_status=fallback_status,
        )

    if materialize_payload:
        return _ScoresExportResolution(
            branch="empty",
            search_status="not_started",
            solutions=[],
            diagnostics=None,
            solutions_held=held_solution_count(
                persisted_row=persisted_row,
                scheduler_run=scheduler_run,
            ),
        )
    return _ScoresExportResolution(
        branch="empty",
        search_status="not_started",
    )


def scores_export_precedence_branch(
    snapshot: ScoresInferenceSnapshot,
) -> ScoresExportPrecedenceBranch:
    """Classify which precedence branch resolves export state for a snapshot."""
    return _resolve_scores_export(snapshot, materialize_payload=False).branch


def is_scores_inference_ensure_satisfied(snapshot: ScoresInferenceSnapshot) -> bool:
    """True when no further ensure work is needed for this snapshot."""
    return scores_export_precedence_branch(snapshot) != "empty"


def resolve_scores_export_search_status(snapshot: ScoresInferenceSnapshot) -> SearchStatus:
    """Resolve search status from the export precedence ladder without materializing solutions."""
    return _resolve_scores_export(snapshot, materialize_payload=False).search_status


def resolve_scores_export_payload(snapshot: ScoresInferenceSnapshot) -> ScoresExportPayload:
    """Resolve search status and solution sources from one precedence ladder."""
    return _resolve_scores_export(snapshot, materialize_payload=True).as_payload()
