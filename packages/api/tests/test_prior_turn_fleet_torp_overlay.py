"""Tests for prior-turn fleet torp overlay consumer (#133)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    resolve_prior_turn_fleet_torp_overlay,
)

from tests.export_chain_test_fixtures import export_chain_query_context, seed_fleet_unwind_through


def test_resolve_prior_turn_overlay_returns_none_on_first_turn(first_turn):
    ctx = export_chain_query_context(first_turn)
    overlay = resolve_prior_turn_fleet_torp_overlay(
        turn=first_turn,
        player_id=8,
        load_turn=ctx.load_turn,
        query_context=ctx,
    )
    assert overlay.overlay is None
    assert overlay.input_status == "not_applicable"


def test_resolve_prior_turn_overlay_readonly_skips_query_when_unpersisted(sample_turn, persistence):
    player_id = 8
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
    )

    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=sample_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )

    assert resolution.overlay is None
    assert resolution.input_status == "pending"


def test_resolve_prior_turn_overlay_readonly_uses_persisted_snapshot(sample_turn, persistence):
    player_id = 8
    prior_turn = sample_turn.settings.turn - 1
    prior_turn_obj = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=prior_turn),
        game=replace(sample_turn.game, turn=prior_turn),
    )
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        seed_fleet_prerequisites_for=player_id,
    )
    fleet_services = ctx.export_services["fleet"]
    snapshot = get_or_materialize_fleet_snapshot(
        fleet_services.persistence,
        ctx.game_id,
        ctx.perspective,
        prior_turn_obj,
        load_turn=ctx.load_turn,
        inference_materialization=fleet_services.inference_materialization,
    )
    snapshot.players = [
        FleetAcquisitionLedger(
            player_id=player_id,
            records=[
                FleetShipRecord(
                    record_id="inferred",
                    disposition="active",
                    fields=FleetShipRecordFields(launchers=FleetFieldUnknown()),
                    build_option_sets=[
                        FleetBuildOptionSet(torp_id=4, label="Mk IV"),
                        FleetBuildOptionSet(torp_id=8, label="Mk VIII"),
                    ],
                ),
            ],
        ),
    ]
    fleet_services.persistence.put_snapshot(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        snapshot,
    )

    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=sample_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )

    assert resolution.overlay is not None
    assert resolution.overlay.belief_set.torp_ids == frozenset({4, 8})
    assert resolution.input_status == "applied"


def test_resolve_prior_turn_overlay_without_export_services_returns_none(sample_turn):
    ctx = export_chain_query_context(sample_turn)
    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=sample_turn,
        player_id=8,
        load_turn=ctx.load_turn,
        export_services=None,
    )
    assert resolution.overlay is None
    assert resolution.input_status == "unavailable"


def test_resolve_prior_turn_overlay_uses_export_services(sample_turn, persistence):
    player_id = 8
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
    )
    seed_fleet_unwind_through(ctx, through_turn=sample_turn.settings.turn, player_id=player_id)

    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=sample_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
    )

    assert resolution.overlay is not None
    assert resolution.overlay.enabled is True
    assert resolution.overlay.belief_set.torp_ids == frozenset({10})
    assert resolution.input_status == "applied"
