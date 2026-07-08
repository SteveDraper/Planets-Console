"""Tests for prior-turn fleet torp overlay consumer (#133)."""

from __future__ import annotations

from dataclasses import replace

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


def test_resolve_prior_turn_overlay_readonly_pending_on_partial_ledger(sample_turn, persistence):
    """Partial prior-turn fleet ledger is not terminal quality; overlay stays pending."""
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
                    ],
                ),
            ],
        ),
    ]
    fleet_services.persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        player_id,
        PersistedFleetLedger(
            ledger=next(ledger for ledger in snapshot.players if ledger.player_id == player_id),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=False,
            ),
        ),
    )
    assert fleet_services.persistence.has_ledger(
        ctx.game_id, ctx.perspective, prior_turn, player_id
    )
    assert not fleet_services.persistence.has_final_ledger(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        player_id,
    )

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
    fleet_services = ctx.export_services["fleet"]
    target_ledger = FleetAcquisitionLedger(
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
    )
    fleet_services.persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        player_id,
        PersistedFleetLedger(
            ledger=target_ledger,
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
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


def test_scores_tier_wire_applies_prior_fleet_dependency_output(sample_turn, persistence):
    from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.compute_orchestration import build_scores_tier_solve_job_wire
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.compute.scope import ComputeScope
    from api.compute.wire import DependencyOutputs

    reset_tier_row_run_registry_for_tests()
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
    prior_persisted = fleet_services.persistence.get_ledger(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        player_id,
    )
    assert prior_persisted is not None

    score = next(row for row in host_turn.scores if row.ownerid == player_id)
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, host_turn),
        turn=host_turn,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=host_turn.settings.turn,
        fleet_torp_input_status="pending",
    )
    run = RowRun(session)
    register_row_run(run)

    prior_fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=prior_turn,
        player_id=player_id,
    )
    dependency_outputs = DependencyOutputs()
    dependency_outputs.put(
        prior_fleet_scope,
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(prior_persisted)},
    )

    build_scores_tier_solve_job_wire(
        ComputeScope(
            analytic_id="scores",
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=host_turn.settings.turn,
            player_id=player_id,
        ),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )

    assert run.session.fleet_torp_input_status == "applied"
    assert run.session.fleet_torp_overlay is not None
    assert run.session.fleet_torp_overlay.belief_set.torp_ids == frozenset({4, 8})


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


def test_background_warm_skips_players_with_final_ledger(
    sample_turn,
    monkeypatch,
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

    submitted: list[object] = []

    def capture_submit(self, request):
        submitted.append(request)
        from api.compute.orchestrator import ComputeHandle

        return ComputeHandle(scope=request.scope, _node=None)

    monkeypatch.setattr(
        "api.compute.orchestrator.ComputeOrchestrator.submit",
        capture_submit,
    )

    schedule_background_prior_turn_fleet_warm(
        turn=host_turn,
        load_turn=fleet_services.load_turn,
        export_services={"fleet": fleet_services},
        player_ids=(player_id,),
    )

    assert submitted == []


def test_background_warm_submits_orchestrator_background_requests(
    sample_turn,
    monkeypatch,
):
    player_id = sample_turn.scores[0].ownerid
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    fleet_services = build_ephemeral_fleet_compute_services(
        host_turn,
        stored_turns=stored_turns,
    )

    submitted: list[object] = []

    def capture_submit(self, request):
        submitted.append(request)
        from api.compute.orchestrator import ComputeHandle

        return ComputeHandle(scope=request.scope, _node=None)

    monkeypatch.setattr(
        "api.compute.orchestrator.ComputeOrchestrator.submit",
        capture_submit,
    )

    schedule_background_prior_turn_fleet_warm(
        turn=host_turn,
        load_turn=fleet_services.load_turn,
        export_services={"fleet": fleet_services},
        player_ids=(player_id,),
    )

    assert len(submitted) == 1
    request = submitted[0]
    assert request.priority_band == "background"
    assert request.scope.analytic_id == "fleet"
    assert request.scope.turn == HOST_TURN - 1
    assert request.scope.player_id == player_id
