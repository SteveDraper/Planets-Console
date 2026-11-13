"""Edges into the fleet walk come only from the walk, for the same player.

A settle keeps a discarded node that other non-running live work still
depends on. For a bump that is a no-op: these edges are why no other
analytic's or other player's work can be that live work. The edges are the
declared catalog edges, the per-scope choice among them, and the
persist-deferred graft from fleet to scores.
"""

from __future__ import annotations

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.exports.registry import EXPORT_REGISTRY
from api.analytics.fleet.compute_orchestration import scores_evidence_recovery
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
from api.compute.scope import ComputeScope

from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import context_at_turn

_PER_SCOPE_CATALOGS = tuple(
    catalog for catalog in EXPORT_REGISTRY.values() if catalog.ensure_dependencies_for is not None
)


def test_only_walk_analytics_ensure_walk_analytics_and_only_for_the_same_player():
    for catalog in EXPORT_REGISTRY.values():
        for dependency in catalog.ensure_dependencies:
            if dependency.analytic_id not in FLEET_WALK_ANALYTIC_IDS:
                continue
            assert catalog.analytic_id in FLEET_WALK_ANALYTIC_IDS, catalog.analytic_id
            assert dependency.player_id == "same", catalog.analytic_id


def test_only_walk_analytics_choose_their_ensure_edges_per_scope():
    per_scope = {catalog.analytic_id for catalog in _PER_SCOPE_CATALOGS}

    assert per_scope <= FLEET_WALK_ANALYTIC_IDS


@pytest.mark.parametrize("backfill_earlier_turns", [False, True], ids=["off", "on"])
def test_per_scope_edges_are_declared_same_player_edges(sample_turn, backfill_earlier_turns):
    """For sample scopes, a per-scope edge choice selects from its catalog's declared edges."""
    _host, ctx = context_at_turn(sample_turn, 41)
    player_id = first_player_id(sample_turn)
    sample_scopes = (
        ExportScope(game_id=ctx.game_id, perspective=ctx.perspective, turn=41, player_id=player_id),
        ExportScope(game_id=ctx.game_id, perspective=ctx.perspective, turn=2, player_id=player_id),
        ExportScope(game_id=ctx.game_id, perspective=ctx.perspective, turn=99, player_id=player_id),
        ExportScope(game_id=ctx.game_id, perspective=ctx.perspective, turn=41),
    )

    for catalog in _PER_SCOPE_CATALOGS:
        for scope in sample_scopes:
            edges = catalog.applicable_ensure_dependencies(
                ctx, scope, backfill_earlier_turns=backfill_earlier_turns
            )
            assert set(edges) <= set(catalog.ensure_dependencies), (catalog.analytic_id, scope)
            assert all(edge.player_id == "same" for edge in edges), (catalog.analytic_id, scope)


@pytest.mark.parametrize(
    "fleet_scope",
    [
        ComputeScope(analytic_id=FLEET_ANALYTIC_ID, game_id=1, perspective=1, turn=40, player_id=7),
        ComputeScope(analytic_id=FLEET_ANALYTIC_ID, game_id=2, perspective=3, turn=1, player_id=11),
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=1,
            perspective=1,
            turn=40,
            player_id=7,
            parameters=(("variant", "x"),),
        ),
    ],
)
def test_the_persist_deferred_graft_stays_on_the_walk_for_the_same_player(fleet_scope):
    grafted = scores_evidence_recovery(fleet_scope).dependency_scope

    assert grafted.analytic_id in FLEET_WALK_ANALYTIC_IDS
    assert grafted.analytic_id != fleet_scope.analytic_id
    assert (grafted.game_id, grafted.perspective, grafted.turn, grafted.player_id) == (
        fleet_scope.game_id,
        fleet_scope.perspective,
        fleet_scope.turn,
        fleet_scope.player_id,
    )
