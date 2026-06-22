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
    search_status_from_wire_complete_event,
    solutions_from_persisted_row,
    solutions_from_scheduler_run,
    solutions_from_terminal_admission,
    wire_complete_event_from_terminal_admission,
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
    """Precedence branch and lifecycle status for one snapshot.

    Attributes:
        needs_ensure_work: Driver for export ensure (prior-turn sync). Today only
            the empty branch sets this; other branches may set it in future.
    """

    branch: ScoresExportPrecedenceBranch
    search_status: SearchStatus
    needs_ensure_work: bool

    @property
    def is_ensure_satisfied(self) -> bool:
        return not self.needs_ensure_work


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
    """Gathered snapshot with precedence decision and payload computed once."""

    snapshot: ScoresInferenceSnapshot
    decision: ScoresExportDecision
    payload: ScoresExportPayload


def resolve_scores_export(snapshot: ScoresInferenceSnapshot) -> ScoresExportResolved:
    decision, payload = _resolve_scores_export_ladder(snapshot)
    return ScoresExportResolved(
        snapshot=snapshot,
        decision=decision,
        payload=payload,
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


def _resolve_scores_export_ladder(
    snapshot: ScoresInferenceSnapshot,
) -> tuple[ScoresExportDecision, ScoresExportPayload]:
    """Single precedence ladder: branch, lifecycle status, and wire payload."""
    persisted_row = snapshot.persisted_row
    scheduler_run = snapshot.scheduler_run

    if persisted_row is not None:
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        if priority_status is not None:
            solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
            return (
                ScoresExportDecision(
                    "priority_persisted",
                    priority_status,
                    needs_ensure_work=False,
                ),
                ScoresExportPayload(solutions, diagnostics, solutions_held),
            )

    terminal = snapshot.resolved_terminal_admission()
    if terminal is not None:
        solutions, diagnostics, solutions_held = solutions_from_terminal_admission(terminal)
        return (
            ScoresExportDecision(
                "terminal_admission",
                search_status_from_wire_complete_event(
                    wire_complete_event_from_terminal_admission(terminal),
                ),
                needs_ensure_work=False,
            ),
            ScoresExportPayload(solutions, diagnostics, solutions_held),
        )

    if scheduler_run is not None:
        solutions, diagnostics, solutions_held = solutions_from_scheduler_run(scheduler_run)
        return (
            ScoresExportDecision(
                "scheduler",
                _search_status_from_scheduler(
                    scheduler_run,
                    globally_paused=snapshot.globally_paused,
                ),
                needs_ensure_work=False,
            ),
            ScoresExportPayload(solutions, diagnostics, solutions_held),
        )

    if persisted_row is not None:
        solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
        return (
            ScoresExportDecision(
                "fallback_persisted",
                _persisted_row_fallback_search_status(persisted_row.status),
                needs_ensure_work=False,
            ),
            ScoresExportPayload(solutions, diagnostics, solutions_held),
        )

    return (
        ScoresExportDecision("empty", "not_started", needs_ensure_work=True),
        ScoresExportPayload([], None, 0),
    )


def is_scores_export_authoritatively_persisted(resolved: ScoresExportResolved) -> bool:
    """True when a persisted inference row authoritatively completes this scope."""
    decision = resolved.decision
    return (
        decision.branch in _AUTHORITATIVE_PERSISTED_BRANCHES
        and decision.search_status == "complete"
    )
