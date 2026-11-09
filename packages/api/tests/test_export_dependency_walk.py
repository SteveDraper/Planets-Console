"""Unit tests for export dependency walk ensure-satisfaction hooks."""

from __future__ import annotations

from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import EnsureDependency, ExportScope
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

    result = walk_dependency_tree(
        ctx,
        catalog.analytic_id,
        scope,
        visiting=set(),
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

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

    result = walk_dependency_tree(
        ctx,
        catalog.analytic_id,
        scope,
        visiting=set(),
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

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

    result = walk_dependency_tree(
        ctx,
        catalog.analytic_id,
        scope,
        visiting=set(),
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

    assert len(result.missing_steps) == 1
    assert result.missing_steps[0].analytic_id == "needs-work"
    assert result.pending_ensure == [(catalog.analytic_id, scope, catalog)]


def test_walk_includes_unsatisfied_turn_one_despite_prior_turn_dep(sample_turn):
    """Turn-1 roots with turn_delta=-1 must still pending-ensure when unsatisfied.

    Eliding those roots as baseline left orchestrator DAG plan empty and
    synthesized a complete node without running homeworld baseline/refine (#204).
    """
    from dataclasses import replace

    from api.analytics.export_types import EnsureDependency
    from api.analytics.exports.catalog import AnalyticExportCatalog

    catalog = AnalyticExportCatalog(
        analytic_id="turn-one-root",
        ensure_dependencies=(
            EnsureDependency(analytic_id="turn-one-root", turn_delta=-1, player_id="same"),
        ),
        ensure_export=lambda _ctx, _scope: False,
        materialize_export_tree=lambda _ctx, _scope: {},
        is_persisted=lambda _ctx, _scope: False,
        is_ensure_satisfied=lambda _ctx, _scope: False,
    )
    turn_one = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
    )
    ctx = make_fixture_query_context(
        turn_one,
        registry={catalog.analytic_id: catalog},
        stored_turns={1: turn_one},
    )
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=1,
        player_id=first_player_id(turn_one),
    )

    result = walk_dependency_tree(
        ctx,
        catalog.analytic_id,
        scope,
        visiting=set(),
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

    assert result.turn_unavailable is None
    assert result.pending_ensure == [(catalog.analytic_id, scope, catalog)]


def _satisfied_root_over(
    sample_turn,
    *,
    is_dependency_satisfied: bool,
    backfill_rewalks_satisfied_scope: bool,
):
    dependency = _catalog("leaf", is_ensure_satisfied=is_dependency_satisfied)
    root = AnalyticExportCatalog(
        analytic_id="satisfied-root",
        ensure_dependencies=(
            EnsureDependency(analytic_id=dependency.analytic_id, turn_delta=0, player_id="same"),
        ),
        ensure_export=lambda _ctx, _scope: False,
        materialize_export_tree=lambda _ctx, _scope: {},
        is_persisted=lambda _ctx, _scope: True,
        is_ensure_satisfied=lambda _ctx, _scope: True,
        backfill_rewalks_satisfied_scope=backfill_rewalks_satisfied_scope,
    )
    ctx = make_fixture_query_context(
        sample_turn,
        registry={root.analytic_id: root, dependency.analytic_id: dependency},
    )
    root_scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )
    return ctx, root, dependency, root_scope


def _walk(ctx, catalog, scope, *, backfill_earlier_turns: bool):
    return walk_dependency_tree(
        ctx,
        catalog.analytic_id,
        scope,
        visiting=set(),
        backfill_earlier_turns=backfill_earlier_turns,
    )


def test_satisfied_scope_that_rewalks_queues_itself_after_dependency_work(sample_turn):
    ctx, root, dependency, scope = _satisfied_root_over(
        sample_turn,
        is_dependency_satisfied=False,
        backfill_rewalks_satisfied_scope=True,
    )

    result = _walk(ctx, root, scope, backfill_earlier_turns=True)

    assert result.pending_ensure == [
        (dependency.analytic_id, scope, dependency),
        (root.analytic_id, scope, root),
    ]
    assert [step.analytic_id for step in result.missing_steps] == [
        dependency.analytic_id,
        root.analytic_id,
    ]


def test_satisfied_scope_that_rewalks_is_not_requeued_without_dependency_work(sample_turn):
    ctx, root, _dependency, scope = _satisfied_root_over(
        sample_turn,
        is_dependency_satisfied=True,
        backfill_rewalks_satisfied_scope=True,
    )

    result = _walk(ctx, root, scope, backfill_earlier_turns=True)

    assert result.missing_steps == []
    assert result.pending_ensure == []


def test_satisfied_scope_rewalks_only_with_backfill_on(sample_turn):
    ctx, root, _dependency, scope = _satisfied_root_over(
        sample_turn,
        is_dependency_satisfied=False,
        backfill_rewalks_satisfied_scope=True,
    )

    result = _walk(ctx, root, scope, backfill_earlier_turns=False)

    assert result.missing_steps == []
    assert result.pending_ensure == []


def test_satisfied_scope_ends_the_walk_unless_its_catalog_rewalks(sample_turn):
    ctx, root, _dependency, scope = _satisfied_root_over(
        sample_turn,
        is_dependency_satisfied=False,
        backfill_rewalks_satisfied_scope=False,
    )

    result = _walk(ctx, root, scope, backfill_earlier_turns=True)

    assert result.missing_steps == []
    assert result.pending_ensure == []
