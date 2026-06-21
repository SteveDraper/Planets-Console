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
from api.analytics.scores.export_wire import (
    held_solution_count,
    solutions_from_admission_or_scheduler,
    solutions_from_persisted_row,
    terminal_row_admission,
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
_AUTHORITATIVE_PERSISTED_BRANCHES = frozenset({"priority_persisted", "fallback_persisted"})


@dataclass(frozen=True)
class ScoresInferenceSnapshot:
    """Gathered inference state for scores export persistence and materialization."""

    persisted_row: PersistedInferenceRow | None
    admission: RowStreamAdmission | None
    scheduler_run: RowRun | None
    globally_paused: bool


@dataclass(frozen=True)
class ScoresExportClassification:
    """Precedence branch and lifecycle status for one inference snapshot."""

    branch: ScoresExportPrecedenceBranch
    search_status: SearchStatus


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


def classify_scores_export(snapshot: ScoresInferenceSnapshot) -> ScoresExportClassification:
    """Classify precedence branch and search status without materializing solutions."""
    persisted_row = snapshot.persisted_row
    admission = snapshot.admission
    scheduler_run = snapshot.scheduler_run

    if persisted_row is not None:
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        if priority_status is not None:
            return ScoresExportClassification("priority_persisted", priority_status)

    if terminal_row_admission(admission) is not None:
        return ScoresExportClassification("terminal_admission", "complete")

    if scheduler_run is not None:
        return ScoresExportClassification(
            "scheduler",
            _search_status_from_scheduler(
                scheduler_run,
                globally_paused=snapshot.globally_paused,
            ),
        )

    if persisted_row is not None:
        return ScoresExportClassification(
            "fallback_persisted",
            _persisted_row_fallback_search_status(persisted_row.status),
        )

    return ScoresExportClassification("empty", "not_started")


def build_scores_export_payload(
    classification: ScoresExportClassification,
    snapshot: ScoresInferenceSnapshot,
) -> ScoresExportPayload:
    """Materialize solutions and diagnostics for one precedence classification."""
    search_status = classification.search_status
    persisted_row = snapshot.persisted_row

    if classification.branch in _AUTHORITATIVE_PERSISTED_BRANCHES:
        assert persisted_row is not None
        solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
        return ScoresExportPayload(
            search_status=search_status,
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    if classification.branch == "terminal_admission":
        solutions, diagnostics, solutions_held = solutions_from_admission_or_scheduler(
            admission=snapshot.admission,
            scheduler_run=snapshot.scheduler_run,
            persisted_row=persisted_row,
        )
        return ScoresExportPayload(
            search_status=search_status,
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    if classification.branch == "scheduler":
        solutions, diagnostics, solutions_held = solutions_from_admission_or_scheduler(
            admission=None,
            scheduler_run=snapshot.scheduler_run,
            persisted_row=persisted_row,
        )
        return ScoresExportPayload(
            search_status=search_status,
            solutions=solutions,
            diagnostics=diagnostics,
            solutions_held=solutions_held,
        )

    return ScoresExportPayload(
        search_status=search_status,
        solutions=[],
        diagnostics=None,
        solutions_held=held_solution_count(
            persisted_row=persisted_row,
            scheduler_run=snapshot.scheduler_run,
        ),
    )


def scores_export_precedence_branch(
    snapshot: ScoresInferenceSnapshot,
) -> ScoresExportPrecedenceBranch:
    """Classify which precedence branch resolves export state for a snapshot."""
    return classify_scores_export(snapshot).branch


def is_scores_inference_ensure_satisfied(snapshot: ScoresInferenceSnapshot) -> bool:
    """True when no further ensure work is needed for this snapshot."""
    return classify_scores_export(snapshot).branch != "empty"


def is_scores_export_authoritatively_persisted(snapshot: ScoresInferenceSnapshot) -> bool:
    """True when a persisted inference row authoritatively completes this scope."""
    classification = classify_scores_export(snapshot)
    return (
        classification.branch in _AUTHORITATIVE_PERSISTED_BRANCHES
        and classification.search_status == "complete"
    )


def resolve_scores_export_search_status(snapshot: ScoresInferenceSnapshot) -> SearchStatus:
    """Resolve search status from the export precedence ladder without materializing solutions."""
    return classify_scores_export(snapshot).search_status


def resolve_scores_export_payload(snapshot: ScoresInferenceSnapshot) -> ScoresExportPayload:
    """Resolve search status and solution sources from one precedence ladder."""
    classification = classify_scores_export(snapshot)
    return build_scores_export_payload(classification, snapshot)
