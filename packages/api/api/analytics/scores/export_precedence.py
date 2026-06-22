"""Export precedence classification and payload resolution for scores inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_SOLVER_ERROR,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
)
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.analytics.scores.export_wire import (
    solutions_from_persisted_row,
    solutions_from_scheduler_run,
    solutions_from_terminal_admission,
    terminal_row_admission,
)

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
class ScoresExportDecision:
    """Precedence branch and lifecycle status for one snapshot."""

    branch: ScoresExportPrecedenceBranch
    search_status: SearchStatus
    needs_ensure_work: bool


def is_persistable_inference_status(status: str) -> bool:
    return status in PERSISTABLE_INFERENCE_STATUSES


@dataclass(frozen=True)
class ScoresExportPayload:
    """Resolved solution payload for a scores inference snapshot."""

    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None
    solutions_held: int


@dataclass(frozen=True)
class ScoresExportResolved:
    """Gathered snapshot with precedence decision computed once."""

    snapshot: ScoresInferenceSnapshot
    decision: ScoresExportDecision


def resolve_scores_export(snapshot: ScoresInferenceSnapshot) -> ScoresExportResolved:
    return ScoresExportResolved(
        snapshot=snapshot,
        decision=_scores_export_decision(snapshot),
    )


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


def _scores_export_decision(snapshot: ScoresInferenceSnapshot) -> ScoresExportDecision:
    """Single precedence ladder: branch and search status."""
    persisted_row = snapshot.persisted_row
    admission = snapshot.admission
    scheduler_run = snapshot.scheduler_run

    if persisted_row is not None:
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        if priority_status is not None:
            return ScoresExportDecision(
                "priority_persisted",
                priority_status,
                needs_ensure_work=False,
            )

    if terminal_row_admission(admission) is not None:
        return ScoresExportDecision(
            "terminal_admission",
            "complete",
            needs_ensure_work=False,
        )

    if scheduler_run is not None:
        return ScoresExportDecision(
            "scheduler",
            _search_status_from_scheduler(
                scheduler_run,
                globally_paused=snapshot.globally_paused,
            ),
            needs_ensure_work=False,
        )

    if persisted_row is not None:
        return ScoresExportDecision(
            "fallback_persisted",
            _persisted_row_fallback_search_status(persisted_row.status),
            needs_ensure_work=False,
        )

    return ScoresExportDecision("empty", "not_started", needs_ensure_work=True)


def _build_scores_export_payload(
    snapshot: ScoresInferenceSnapshot,
    decision: ScoresExportDecision,
) -> ScoresExportPayload:
    """Materialize solutions and diagnostics for one precedence branch."""
    match decision.branch:
        case "priority_persisted" | "fallback_persisted":
            persisted_row = snapshot.persisted_row
            assert persisted_row is not None
            solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
        case "terminal_admission":
            terminal = terminal_row_admission(snapshot.admission)
            assert terminal is not None
            solutions, diagnostics, solutions_held = solutions_from_terminal_admission(terminal)
        case "scheduler":
            scheduler_run = snapshot.scheduler_run
            assert scheduler_run is not None
            solutions, diagnostics, solutions_held = solutions_from_scheduler_run(scheduler_run)
        case "empty":
            solutions, diagnostics = [], None
            solutions_held = 0
    return ScoresExportPayload(
        solutions=solutions,
        diagnostics=diagnostics,
        solutions_held=solutions_held,
    )


def is_scores_inference_ensure_satisfied(resolved: ScoresExportResolved) -> bool:
    """True when no further ensure work is needed for this snapshot."""
    return not resolved.decision.needs_ensure_work


def is_scores_export_authoritatively_persisted(resolved: ScoresExportResolved) -> bool:
    """True when a persisted inference row authoritatively completes this scope."""
    decision = resolved.decision
    return (
        decision.branch in _AUTHORITATIVE_PERSISTED_BRANCHES
        and decision.search_status == "complete"
    )


def resolve_scores_export_payload(resolved: ScoresExportResolved) -> ScoresExportPayload:
    """Resolve solution sources from one stored precedence decision."""
    return _build_scores_export_payload(resolved.snapshot, resolved.decision)
