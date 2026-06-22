"""Unit tests for export dependency walk ensure-satisfaction hooks."""

from __future__ import annotations

from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import ExportScope
from api.analytics.exports.catalog import AnalyticExportCatalog

from tests.fixtures.export_framework.harness import first_player_id, make_fixture_query_context


def _catalog(
    analytic_id: str,
    *,
    is_persisted: bool = False,
    is_ensure_satisfied: bool | None = None,
) -> AnalyticExportCatalog:
    return AnalyticExportCatalog(
        analytic_id=analytic_id,
        ensure_export=lambda _ctx, _scope: False,
        materialize_export_tree=lambda _ctx, _scope: {},
        is_persisted=lambda _ctx, _scope: is_persisted,
        is_ensure_satisfied=(
            None if is_ensure_satisfied is None else (lambda _ctx, _scope: is_ensure_satisfied)
        ),
    )


def test_walk_uses_is_ensure_satisfied_when_present(sample_turn):
    player_id = first_player_id(sample_turn)
    catalog = _catalog("split-hook", is_persisted=False, is_ensure_satisfied=True)
    ctx = make_fixture_query_context(
        sample_turn,
        registry={catalog.analytic_id: catalog},
    )
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    result = walk_dependency_tree(ctx, catalog.analytic_id, scope, visiting=set())

    assert result.missing_steps == []
    assert result.pending_ensure == []


def test_walk_falls_back_to_is_persisted_without_is_ensure_satisfied(sample_turn):
    player_id = first_player_id(sample_turn)
    catalog = _catalog("persisted-only", is_persisted=True)
    ctx = make_fixture_query_context(
        sample_turn,
        registry={catalog.analytic_id: catalog},
    )
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    result = walk_dependency_tree(ctx, catalog.analytic_id, scope, visiting=set())

    assert result.missing_steps == []
    assert result.pending_ensure == []


def test_walk_reports_missing_when_neither_hook_satisfied(sample_turn):
    player_id = first_player_id(sample_turn)
    catalog = _catalog("needs-work", is_persisted=False, is_ensure_satisfied=False)
    ctx = make_fixture_query_context(
        sample_turn,
        registry={catalog.analytic_id: catalog},
    )
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    result = walk_dependency_tree(ctx, catalog.analytic_id, scope, visiting=set())

    assert len(result.missing_steps) == 1
    assert result.missing_steps[0].analytic_id == "needs-work"
    assert result.pending_ensure == [(catalog.analytic_id, scope, catalog)]
