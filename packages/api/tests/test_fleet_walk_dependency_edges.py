"""Ensure edges into the fleet walk come only from the walk, for the same player.

A bump settles one player's fleet and scores work. Its needed exemption keeps
a discarded node that other live work still depends on. These edges are why
no other analytic's or other player's work can be that live work.
"""

from __future__ import annotations

from api.analytics.exports.registry import EXPORT_REGISTRY
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS


def test_only_walk_analytics_ensure_walk_analytics_and_only_for_the_same_player():
    for catalog in EXPORT_REGISTRY.values():
        for dependency in catalog.ensure_dependencies:
            if dependency.analytic_id not in FLEET_WALK_ANALYTIC_IDS:
                continue
            assert catalog.analytic_id in FLEET_WALK_ANALYTIC_IDS, catalog.analytic_id
            assert dependency.player_id == "same", catalog.analytic_id


def test_only_walk_analytics_choose_their_ensure_edges_per_scope():
    """A per-scope edge choice selects from its catalog's declared edges."""
    per_scope = {
        catalog.analytic_id
        for catalog in EXPORT_REGISTRY.values()
        if catalog.ensure_dependencies_for is not None
    }

    assert per_scope <= FLEET_WALK_ANALYTIC_IDS
