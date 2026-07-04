"""Tests for prior-turn fleet torp overlay consumer (#133)."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from api.analytics.fleet.chain import (
    ensure_fleet_baseline_for_player,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetFieldUnknown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    resolve_prior_turn_fleet_torp_overlay,
    schedule_background_prior_turn_fleet_warm,
)
from api.errors import ConflictError

from tests.export_chain_test_fixtures import export_chain_query_context, seed_fleet_unwind_through
from tests.fleet_chain_test_turns import HOST_TURN
from tests.fleet_exports_helpers import host_turn_at


def _host_turn_context(sample_turn, persistence, *, seed_player_ids: int | None = None):
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    kwargs: dict[str, object] = {
        "persistence": persistence,
        "stored_turns": stored_turns,
    }
    if seed_player_ids is not None:
        kwargs["seed_fleet_prerequisites_for"] = seed_player_ids
    ctx = export_chain_query_context(host_turn, **kwargs)
    return host_turn, ctx


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
    host_turn, ctx = _host_turn_context(sample_turn, persistence)

    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )

    assert resolution.overlay is None
    assert resolution.input_status == "pending"


def test_resolve_prior_turn_overlay_readonly_uses_persisted_snapshot(sample_turn, persistence):
    player_id = 8
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_id,
    )
    prior_turn = HOST_TURN - 1
    prior_turn_obj = replace(
        host_turn,
        settings=replace(host_turn.settings, turn=prior_turn),
        game=replace(host_turn.game, turn=prior_turn),
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
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )

    assert resolution.overlay is not None
    assert resolution.overlay.belief_set.torp_ids == frozenset({4, 8})
    assert resolution.input_status == "applied"


def test_resolve_prior_turn_overlay_without_export_services_returns_none(sample_turn):
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    ctx = export_chain_query_context(host_turn, stored_turns=stored_turns)
    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=8,
        load_turn=ctx.load_turn,
        export_services=None,
    )
    assert resolution.overlay is None
    assert resolution.input_status == "unavailable"


def test_resolve_prior_turn_overlay_uses_export_services(sample_turn, persistence):
    player_id = 8
    host_turn, ctx = _host_turn_context(sample_turn, persistence)
    seed_fleet_unwind_through(ctx, through_turn=HOST_TURN, player_id=player_id)

    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
    )

    assert resolution.overlay is not None
    assert resolution.overlay.enabled is True
    assert resolution.overlay.belief_set.torp_ids == frozenset({10})
    assert resolution.input_status == "applied"


def _run_warm_synchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    def immediate_thread(*, target, args=(), daemon=True):
        class _ImmediateThread:
            def start(self) -> None:
                target(*args)

        return _ImmediateThread()

    monkeypatch.setattr(
        "api.analytics.military_score_inference.prior_turn_fleet_torp_overlay.threading.Thread",
        immediate_thread,
    )


def test_background_warm_swallows_conflict_when_prior_turn_snapshot_exists(
    sample_turn,
    monkeypatch,
    caplog,
):
    player_id = 8
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    fleet_services = build_ephemeral_fleet_compute_services(
        host_turn,
        stored_turns=stored_turns,
    )
    prior_turn = HOST_TURN - 1
    prior_turn_info = fleet_services.load_turn(prior_turn)
    assert prior_turn_info is not None
    fleet_services.persistence.put_ledger(
        fleet_services.game_id,
        fleet_services.perspective,
        prior_turn,
        player_id,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(
                fleet_services.game_id,
                fleet_services.perspective,
                prior_turn_info,
                player_id,
            ),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )

    def raise_conflict(*_args, **_kwargs):
        raise ConflictError("fleet snapshot gap-fill exceeded invalidation retries")

    monkeypatch.setattr(
        "api.analytics.fleet.chain.get_or_materialize_fleet_ledger_for_player",
        raise_conflict,
    )
    _run_warm_synchronously(monkeypatch)

    with caplog.at_level(logging.WARNING):
        schedule_background_prior_turn_fleet_warm(
            turn=host_turn,
            load_turn=fleet_services.load_turn,
            export_services={"fleet": fleet_services},
            player_ids=(player_id,),
        )

    assert "Background prior-turn fleet warm failed" not in caplog.text


def test_background_warm_logs_warning_on_conflict_without_prior_turn_snapshot(
    sample_turn,
    monkeypatch,
    caplog,
):
    player_id = sample_turn.scores[0].ownerid
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    fleet_services = build_ephemeral_fleet_compute_services(
        host_turn,
        stored_turns=stored_turns,
    )

    def raise_conflict(*_args, **_kwargs):
        raise ConflictError("fleet snapshot gap-fill exceeded invalidation retries")

    monkeypatch.setattr(
        "api.analytics.fleet.chain.get_or_materialize_fleet_ledger_for_player",
        raise_conflict,
    )
    _run_warm_synchronously(monkeypatch)

    with caplog.at_level(logging.WARNING):
        schedule_background_prior_turn_fleet_warm(
            turn=host_turn,
            load_turn=fleet_services.load_turn,
            export_services={"fleet": fleet_services},
            player_ids=(player_id,),
        )

    assert "Background prior-turn fleet warm failed" in caplog.text
