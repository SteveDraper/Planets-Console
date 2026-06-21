"""Materialize scores export value trees from resolved precedence."""

from __future__ import annotations

from typing import Any

from api.analytics.export_types import ExportScope
from api.analytics.scores.export_precedence import (
    ScoresExportResolved,
    SearchStatus,
    resolve_scores_export_payload,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.models.game import TurnInfo


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


def build_scores_export_materialized_tree(
    resolved: ScoresExportResolved,
    scope: ExportScope,
    *,
    services: ScoresExportContext,
    turn: TurnInfo,
) -> dict[str, Any]:
    """Materialize the full scores export value tree for one resolved snapshot."""
    payload = resolve_scores_export_payload(resolved)
    tree: dict[str, Any] = {
        "meta": _export_meta_branch(
            search_status=resolved.decision.search_status,
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
