"""Compute diagnostic scope resolution for one shell context."""

from __future__ import annotations

from collections.abc import Mapping

from api.analytics.exports.catalog import AnalyticExportCatalog
from api.compute.scope import WILDCARD, ComputeScope


def collect_diagnostic_ancestor_turns(
    shell_turn: int,
    *,
    export_registry: Mapping[str, AnalyticExportCatalog],
    compute_analytic_ids: frozenset[str],
) -> frozenset[int]:
    """Return shell turn plus ancestor turns on registered ENSURE_DEPENDENCIES edges."""
    turns: set[int] = {shell_turn}
    queue: list[tuple[str, int]] = [
        (analytic_id, shell_turn) for analytic_id in compute_analytic_ids
    ]
    seen: set[tuple[str, int]] = set()
    while queue:
        analytic_id, turn = queue.pop()
        visit_key = (analytic_id, turn)
        if visit_key in seen:
            continue
        seen.add(visit_key)
        catalog = export_registry.get(analytic_id)
        if catalog is None:
            continue
        for dependency in catalog.ensure_dependencies:
            dependency_turn = turn + dependency.turn_delta
            if dependency_turn < 1:
                continue
            turns.add(dependency_turn)
            queue.append((dependency.analytic_id, dependency_turn))
    return frozenset(turns)


def scope_in_diagnostic_scope(
    scope: ComputeScope,
    *,
    game_id: int,
    perspective: int,
    ancestor_turns: frozenset[int],
) -> bool:
    """Return whether ``scope`` is visible under one shell diagnostic context."""
    if scope.game_id != game_id:
        return False
    if scope.perspective not in (perspective, WILDCARD):
        return False
    if scope.turn != WILDCARD and scope.turn not in ancestor_turns:
        return False
    return True


def player_id_from_scope(scope: ComputeScope) -> int | None:
    """Return a concrete player id when the scope is player-specific."""
    if scope.player_id == WILDCARD:
        return None
    if isinstance(scope.player_id, int):
        return scope.player_id
    return None
