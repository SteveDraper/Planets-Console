"""Tests for table/map batch compute scope fan-out and routing (#202)."""

from __future__ import annotations

from api.analytics.compute_context import make_analytic_compute_context
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.homeworld_locator.constants import ANALYTIC_ID as HOMEWORLD_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.turn_roster import iter_turn_players
from api.compute.batch_compute import ensure_table_map_compute, table_map_compute_scopes
from api.compute.scope import WILDCARD


def test_table_map_scopes_fan_out_player_axis(sample_turn):
    ctx = make_analytic_compute_context(sample_turn).exports
    scopes = table_map_compute_scopes(FLEET_ANALYTIC_ID, ctx, sample_turn)
    roster_ids = tuple(player.id for player in iter_turn_players(sample_turn))
    assert tuple(scope.player_id for scope in scopes) == roster_ids
    assert all(scope.analytic_id == FLEET_ANALYTIC_ID for scope in scopes)
    assert all(scope.turn == sample_turn.settings.turn for scope in scopes)


def test_table_map_scopes_use_request_perspective_not_rst_player(sample_turn):
    """Storage viewpoint is the request perspective, not turn.player.id.

    Sample RST is koshling (player 8) stored under perspective 1. Orchestrator
    scopes must hit that slot or table/map ensure misses seeded ledgers.
    """
    ctx = make_analytic_compute_context(
        sample_turn,
        game_id=628580,
        perspective=1,
    ).exports
    scopes = table_map_compute_scopes(FLEET_ANALYTIC_ID, ctx, sample_turn)
    assert ctx.perspective == 1
    assert sample_turn.player.id != 1
    assert all(scope.perspective == 1 for scope in scopes)


def test_table_map_scopes_single_unscoped_for_homeworld(sample_turn):
    ctx = make_analytic_compute_context(sample_turn).exports
    scopes = table_map_compute_scopes(HOMEWORLD_ANALYTIC_ID, ctx, sample_turn)
    assert len(scopes) == 1
    assert scopes[0].analytic_id == HOMEWORLD_ANALYTIC_ID
    assert scopes[0].player_id == WILDCARD
    assert scopes[0].turn == sample_turn.settings.turn


def test_ensure_table_map_compute_skips_scores(sample_turn, monkeypatch):
    def fail_orchestrator(**_kwargs):
        raise AssertionError("scores REST must not submit table/map compute")

    monkeypatch.setattr(
        "api.compute.runtime.get_compute_orchestrator",
        fail_orchestrator,
    )
    ctx = make_analytic_compute_context(sample_turn).exports
    ensure_table_map_compute(ctx, SCORES_ANALYTIC_ID, sample_turn)


def test_ensure_table_map_compute_skips_unregistered(sample_turn, monkeypatch):
    def fail_orchestrator(**_kwargs):
        raise AssertionError("unregistered analytics must not submit table/map compute")

    monkeypatch.setattr(
        "api.compute.runtime.get_compute_orchestrator",
        fail_orchestrator,
    )
    ctx = make_analytic_compute_context(sample_turn).exports
    ensure_table_map_compute(ctx, "base-map", sample_turn)
