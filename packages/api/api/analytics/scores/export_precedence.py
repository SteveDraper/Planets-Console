"""Export precedence classification and payload resolution for scores inference."""

from __future__ import annotations

from collections.abc import Callable
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
    STATUS_TIME_LIMITED,
)
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.analytics.scores.export_wire import (
    search_status_from_wire_complete_event,
    solutions_from_persisted_row,
    solutions_from_scheduler_run,
    solutions_from_terminal_admission,
    wire_complete_event_from_terminal_admission,
)
from api.analytics.scores.host_turn_export import (
    FunctionalHostTurnPayload,
    resolve_functional_host_turn_payload,
)
from api.models.game import TurnInfo
from api.models.player import Score
from api.serialization.inference_row_persistence import PersistedInferenceRow

SearchStatus = Literal["not_started", "in_progress", "paused", "stopped", "complete"]
ScoresExportPrecedenceBranch = Literal[
    "priority_persisted",
    "terminal_admission",
    "scheduler",
    "fallback_persisted",
    "functional_backfill",
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
# RowComplete statuses that, once on disk, close fleet turnEvidenceAtN
# (priority complete/stopped or fallback-complete). Orchestrator tier_solve must
# persist these rather than soft-completing the scores node with open evidence.
_PRIORITY_STOPPED_PERSISTED_STATUSES = frozenset({STATUS_STOPPED, STATUS_TIME_LIMITED})
DURABLE_TURN_EVIDENCE_ROW_STATUSES = (
    PERSISTABLE_INFERENCE_STATUSES
    | _PRIORITY_STOPPED_PERSISTED_STATUSES
    | _FALLBACK_COMPLETE_PERSISTED_STATUSES
)
_AUTHORITATIVE_PERSISTED_BRANCHES = frozenset({"priority_persisted", "fallback_persisted"})


@dataclass(frozen=True)
class ScoresExportDecision:
    """Precedence branch and lifecycle status for one snapshot.

    Attributes:
        needs_ensure_work: Driver for export ensure (schedule RowRun when empty).
            Today only the empty branch sets this; other branches may set it in future.
    """

    branch: ScoresExportPrecedenceBranch
    search_status: SearchStatus
    needs_ensure_work: bool

    @property
    def is_ensure_satisfied(self) -> bool:
        """True when probe/ensure should skip further admit work for this scope.

        Includes an in-progress scheduler ``RowRun`` (attach, do not re-schedule).
        That is weaker than terminal scores evidence -- see ``is_turn_evidence_closed``.
        """
        return not self.needs_ensure_work

    @property
    def is_turn_evidence_closed(self) -> bool:
        """True when scores@N is terminal for fleet ``turnEvidenceAtN``.

        A scheduled / in-progress ``RowRun`` (``scheduler`` branch) is ensure-satisfied
        for admit idempotency but must not close fleet turn evidence: scores persist
        later invalidates fleet ledgers from that host turn.
        """
        if self.branch in {"empty", "scheduler"}:
            return False
        return self.search_status in {"complete", "stopped"}


def is_persistable_inference_status(status: str) -> bool:
    return status in PERSISTABLE_INFERENCE_STATUSES


def is_durable_turn_evidence_row_status(status: str) -> bool:
    """True when persisting this RowComplete status closes scores turn evidence."""
    return status in DURABLE_TURN_EVIDENCE_ROW_STATUSES


@dataclass(frozen=True)
class ScoresExportResolutionContext:
    """Turn and persistence context for host-turn functional export normalization."""

    scoreboard_turn: int
    turn: TurnInfo
    player_id: int | None
    load_scoreboard_turn: Callable[[int], TurnInfo | None]
    get_persisted_row: Callable[[int, int], PersistedInferenceRow | None] | None = None
    player_score: Score | None = None


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


def classify_scores_export_branch(
    snapshot: ScoresInferenceSnapshot,
    *,
    resolution_context: ScoresExportResolutionContext,
    functional_payload: FunctionalHostTurnPayload | None,
) -> ScoresExportPrecedenceBranch:
    """Classify precedence branch from gathered state without materializing payloads."""
    persisted_row = snapshot.persisted_row
    if persisted_row is not None:
        if _persisted_row_priority_search_status(persisted_row.status) is not None:
            return "priority_persisted"

    if snapshot.resolved_terminal_admission() is not None:
        return "terminal_admission"

    if snapshot.scheduler_run is not None:
        return "scheduler"

    if persisted_row is not None:
        return "fallback_persisted"

    if functional_payload is not None:
        return "functional_backfill"

    return "empty"


def classify_scores_export_decision(
    snapshot: ScoresInferenceSnapshot,
    *,
    resolution_context: ScoresExportResolutionContext,
    functional_payload: FunctionalHostTurnPayload | None,
) -> ScoresExportDecision:
    """Resolve branch and lifecycle status without materializing solution payloads."""
    branch = classify_scores_export_branch(
        snapshot,
        resolution_context=resolution_context,
        functional_payload=functional_payload,
    )
    if branch == "priority_persisted":
        persisted_row = snapshot.persisted_row
        assert persisted_row is not None
        priority_status = _persisted_row_priority_search_status(persisted_row.status)
        assert priority_status is not None
        return ScoresExportDecision(branch, priority_status, needs_ensure_work=False)

    if branch == "terminal_admission":
        terminal = snapshot.resolved_terminal_admission()
        assert terminal is not None
        return ScoresExportDecision(
            branch,
            search_status_from_wire_complete_event(
                wire_complete_event_from_terminal_admission(terminal),
            ),
            needs_ensure_work=False,
        )

    if branch == "scheduler":
        scheduler_run = snapshot.scheduler_run
        assert scheduler_run is not None
        return ScoresExportDecision(
            branch,
            _search_status_from_scheduler(
                scheduler_run,
                globally_paused=snapshot.globally_paused,
            ),
            needs_ensure_work=False,
        )

    if branch == "fallback_persisted":
        persisted_row = snapshot.persisted_row
        assert persisted_row is not None
        return ScoresExportDecision(
            branch,
            _persisted_row_fallback_search_status(persisted_row.status),
            needs_ensure_work=False,
        )

    if branch == "functional_backfill":
        assert functional_payload is not None
        return ScoresExportDecision(
            branch,
            functional_payload.search_status,
            needs_ensure_work=False,
        )

    return ScoresExportDecision("empty", "not_started", needs_ensure_work=True)


def is_scores_export_ensure_satisfied_from_snapshot(
    snapshot: ScoresInferenceSnapshot,
    *,
    resolution_context: ScoresExportResolutionContext,
) -> bool:
    """True when probe/ensure walks should skip this scope (no further ensure work)."""
    functional_payload = _resolve_functional_payload(snapshot, resolution_context)
    return not classify_scores_export_decision(
        snapshot,
        resolution_context=resolution_context,
        functional_payload=functional_payload,
    ).needs_ensure_work


def is_scores_export_turn_evidence_closed_from_snapshot(
    snapshot: ScoresInferenceSnapshot,
    *,
    resolution_context: ScoresExportResolutionContext,
) -> bool:
    """True when scores@N is terminal enough to close fleet ``turnEvidenceAtN``.

    Distinct from ``is_scores_export_ensure_satisfied_from_snapshot``: an in-progress
    scheduler ``RowRun`` satisfies ensure admit but does not close turn evidence.
    """
    functional_payload = _resolve_functional_payload(snapshot, resolution_context)
    return classify_scores_export_decision(
        snapshot,
        resolution_context=resolution_context,
        functional_payload=functional_payload,
    ).is_turn_evidence_closed


def resolve_scores_export(
    snapshot: ScoresInferenceSnapshot,
    *,
    resolution_context: ScoresExportResolutionContext,
) -> ScoresExportResolved:
    decision, payload = _resolve_scores_export_ladder(
        snapshot,
        resolution_context=resolution_context,
    )
    return ScoresExportResolved(
        snapshot=snapshot,
        decision=decision,
        payload=payload,
    )


def _persisted_row_priority_search_status(status: str) -> SearchStatus | None:
    """Persisted statuses that override live admission or scheduler state."""
    if status in PERSISTABLE_INFERENCE_STATUSES:
        return "complete"
    if status in _PRIORITY_STOPPED_PERSISTED_STATUSES:
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
    *,
    resolution_context: ScoresExportResolutionContext,
) -> tuple[ScoresExportDecision, ScoresExportPayload]:
    """Single precedence ladder: branch, lifecycle status, and wire payload."""
    functional_payload = _resolve_functional_payload(snapshot, resolution_context)
    decision = classify_scores_export_decision(
        snapshot,
        resolution_context=resolution_context,
        functional_payload=functional_payload,
    )
    payload = _materialize_scores_export_payload(
        snapshot,
        decision.branch,
        functional_payload=functional_payload,
    )
    return decision, payload


def _resolve_functional_payload(
    snapshot: ScoresInferenceSnapshot,
    resolution_context: ScoresExportResolutionContext,
) -> FunctionalHostTurnPayload | None:
    return resolve_functional_host_turn_payload(
        scoreboard_turn=resolution_context.scoreboard_turn,
        turn=resolution_context.turn,
        score=resolution_context.player_score,
        persisted_row=snapshot.persisted_row,
        load_scoreboard_turn=resolution_context.load_scoreboard_turn,
        get_persisted_row=resolution_context.get_persisted_row,
    )


def _materialize_scores_export_payload(
    snapshot: ScoresInferenceSnapshot,
    branch: ScoresExportPrecedenceBranch,
    *,
    functional_payload: FunctionalHostTurnPayload | None,
) -> ScoresExportPayload:
    persisted_row = snapshot.persisted_row
    if branch == "priority_persisted":
        assert persisted_row is not None
        if functional_payload is not None:
            return ScoresExportPayload(
                functional_payload.solutions,
                None,
                functional_payload.solutions_held,
            )
        solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
        return ScoresExportPayload(solutions, diagnostics, solutions_held)

    if branch == "terminal_admission":
        terminal = snapshot.resolved_terminal_admission()
        assert terminal is not None
        solutions, diagnostics, solutions_held = solutions_from_terminal_admission(terminal)
        return ScoresExportPayload(solutions, diagnostics, solutions_held)

    if branch == "scheduler":
        scheduler_run = snapshot.scheduler_run
        assert scheduler_run is not None
        solutions, diagnostics, solutions_held = solutions_from_scheduler_run(scheduler_run)
        return ScoresExportPayload(solutions, diagnostics, solutions_held)

    if branch == "fallback_persisted":
        assert persisted_row is not None
        if functional_payload is not None:
            return ScoresExportPayload(
                functional_payload.solutions,
                None,
                functional_payload.solutions_held,
            )
        solutions, diagnostics, solutions_held = solutions_from_persisted_row(persisted_row)
        return ScoresExportPayload(solutions, diagnostics, solutions_held)

    if branch == "functional_backfill":
        assert functional_payload is not None
        return ScoresExportPayload(
            functional_payload.solutions,
            None,
            functional_payload.solutions_held,
        )

    return ScoresExportPayload([], None, 0)


def is_scores_export_authoritatively_persisted(resolved: ScoresExportResolved) -> bool:
    """True when a persisted inference row authoritatively completes this scope."""
    decision = resolved.decision
    return (
        decision.branch in _AUTHORITATIVE_PERSISTED_BRANCHES
        and decision.search_status == "complete"
    )
