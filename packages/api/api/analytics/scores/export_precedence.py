"""Export precedence classification and payload resolution for scores inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from api.analytics.export_types import ExportScope
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
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.analytics.scores.export_wire import (
    held_solution_count,
    solutions_from_admission_or_scheduler,
    solutions_from_persisted_row,
    terminal_row_admission,
)
from api.analytics.scores.inference import get_scores_row_inference
from api.models.game import TurnInfo
from api.serialization.inference_row_persistence import persisted_inference_row_from_wire_complete
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

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


def is_persistable_inference_status(status: str) -> bool:
    return status in PERSISTABLE_INFERENCE_STATUSES


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


@dataclass(frozen=True)
class ScoresExportResolved:
    """Gathered snapshot with precedence classification computed once."""

    snapshot: ScoresInferenceSnapshot
    classification: ScoresExportClassification


def _as_resolved(view: ScoresExportResolved | ScoresInferenceSnapshot) -> ScoresExportResolved:
    if isinstance(view, ScoresExportResolved):
        return view
    return resolve_scores_export(view)


def resolve_scores_export(snapshot: ScoresInferenceSnapshot) -> ScoresExportResolved:
    return ScoresExportResolved(
        snapshot=snapshot,
        classification=classify_scores_export(snapshot),
    )


def _export_meta_branch(
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


def _hull_catalog_mask_branch(enabled_hull_ids: frozenset[int] | set[int]) -> dict[str, object]:
    return {"enabledHullIds": sorted(enabled_hull_ids)}


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

    if classification.branch in ("terminal_admission", "scheduler"):
        # Scheduler branch intentionally ignores non-terminal admission on the snapshot.
        admission = snapshot.admission if classification.branch == "terminal_admission" else None
        solutions, diagnostics, solutions_held = solutions_from_admission_or_scheduler(
            admission=admission,
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


def is_scores_inference_ensure_satisfied(
    view: ScoresExportResolved | ScoresInferenceSnapshot,
) -> bool:
    """True when no further ensure work is needed for this snapshot."""
    return _as_resolved(view).classification.branch != "empty"


def is_scores_export_authoritatively_persisted(
    view: ScoresExportResolved | ScoresInferenceSnapshot,
) -> bool:
    """True when a persisted inference row authoritatively completes this scope."""
    classification = _as_resolved(view).classification
    return (
        classification.branch in _AUTHORITATIVE_PERSISTED_BRANCHES
        and classification.search_status == "complete"
    )


def resolve_scores_export_payload(
    view: ScoresExportResolved | ScoresInferenceSnapshot,
) -> ScoresExportPayload:
    """Resolve search status and solution sources from one precedence ladder."""
    resolved = _as_resolved(view)
    return build_scores_export_payload(resolved.classification, resolved.snapshot)


def build_scores_export_materialized_tree(
    view: ScoresExportResolved | ScoresInferenceSnapshot,
    scope: ExportScope,
    *,
    services: ScoresExportContext,
    turn: TurnInfo,
) -> dict[str, Any]:
    """Materialize the full scores export value tree for one resolved snapshot."""
    payload = resolve_scores_export_payload(view)
    tree: dict[str, Any] = {
        "meta": _export_meta_branch(
            search_status=payload.search_status,
            host_turn=scope.turn,
            solutions_held=payload.solutions_held,
        ),
        "solutions": payload.solutions,
    }
    if payload.diagnostics is not None:
        tree["diagnostics"] = payload.diagnostics

    if scope.player_id is not None:
        resolved_mask = services.resolve_hull_catalog_mask(turn, scope.player_id)
        if resolved_mask is not None:
            tree["hullCatalogMask"] = _hull_catalog_mask_branch(
                resolved_mask.effective_enabled_hull_ids
            )

    return tree


def sync_persist_empty_branch(
    resolved: ScoresExportResolved,
    *,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
    load_scoreboard_turn: Callable[[int], TurnInfo | None],
) -> bool:
    """Persist sync inference when precedence is empty (prior-turn ensure path)."""
    if resolved.classification.branch != "empty":
        return False
    if services.persistence is None or scope.player_id is None:
        return False

    player_id = scope.player_id
    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    inference = get_scores_row_inference(
        turn,
        player_id,
        load_scoreboard_turn=load_scoreboard_turn,
        resolved_mask=resolved_mask,
    )
    status = str(inference.get("status", ""))
    if not is_persistable_inference_status(status):
        return False
    wire_event = inference_api_payload_to_wire_complete(inference)
    row = persisted_inference_row_from_wire_complete(wire_event)
    services.persistence.put_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
        row,
    )
    return True
