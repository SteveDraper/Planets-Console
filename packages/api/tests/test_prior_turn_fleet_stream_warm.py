"""Integration tests for prior-turn fleet warm, invalidation, and diagnostics (#133)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace

import pytest
from api.analytics.fleet.gap_fill_coordinator import reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetLauncherBeliefSet,
    FleetTorpOverlay,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    iter_scores_table_inference_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    resolve_prior_turn_fleet_torp_overlay,
    schedule_background_prior_turn_fleet_warm,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_invalidation_service import InferenceInvalidationService

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.fleet_chain_test_turns import HOST_TURN
from tests.fleet_exports_helpers import host_turn_at


@pytest.fixture(autouse=True)
def _reset_stream_registry_after_test() -> None:
    reset_coordinators()
    yield
    reset_coordinators()
    reset_inference_table_stream_registry_for_tests()


def _wire_fleet_scores_invalidation(
    inference_persistence,
    fleet_persistence: FleetSnapshotPersistenceService,
    scheduler: InferenceRowScheduler,
) -> InferenceInvalidationService:
    invalidation = InferenceInvalidationService(
        inference_persistence,
        scheduler=scheduler,
        fleet_persistence=fleet_persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    return invalidation


def _install_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    *,
    worker_count: int = 0,
) -> InferenceRowScheduler:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=worker_count)

    def _get_scheduler() -> InferenceRowScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler.get_inference_row_scheduler",
        _get_scheduler,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_rows.get_inference_row_scheduler",
        _get_scheduler,
    )
    return scheduler


def test_on_fleet_snapshot_persisted_clears_scores_host_turn_document(
    memory_backend,
    persistence,
):
    """Persisting fleet@(N-1) always drops scores@N cache; reschedule needs an open stream."""
    from unittest.mock import MagicMock

    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.military_score_inference.inference_table_stream_registry import (
        attach_inference_table_stream,
        reset_inference_table_stream_registry_for_tests,
    )

    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    scheduler = InferenceRowScheduler(worker_count=0)
    invalidation = InferenceInvalidationService(
        persistence,
        scheduler=scheduler,
        fleet_persistence=fleet_persistence,
    )

    game_id, persp = 628580, 1
    player_id = 8
    row = PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="cached",
        solution_count=0,
        is_complete=True,
        solutions=[],
    )
    for host_turn in (110, 111):
        persistence.put_row(game_id, persp, host_turn, player_id, row)

    invalidation.on_fleet_snapshot_persisted(game_id, persp, fleet_turn=110)

    assert persistence.get_row(game_id, persp, 111, player_id) is None
    assert persistence.get_row(game_id, persp, 110, player_id) is not None

    persistence.put_row(game_id, persp, 111, player_id, row)

    try:
        scope = InferenceStreamScope(game_id=game_id, perspective=persp, turn_number=111)
        controller = MagicMock()
        controller.scope = scope
        controller.player_ids = (player_id,)
        controller.reschedule_all_rows = MagicMock(return_value=True)
        attach_inference_table_stream(controller)

        invalidation.on_fleet_snapshot_persisted(game_id, persp, fleet_turn=110)

        assert persistence.get_row(game_id, persp, 111, player_id) is None
        controller.reschedule_all_rows.assert_called_once()
    finally:
        reset_inference_table_stream_registry_for_tests()


def _fleet_overlay_from_diagnostics(diagnostics: object) -> dict[str, object]:
    assert isinstance(diagnostics, dict)
    fleet_overlay = diagnostics.get("fleetTorpOverlay")
    assert isinstance(fleet_overlay, dict)
    return fleet_overlay


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


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


def _run_ids_for_players(
    scheduler: InferenceRowScheduler,
    player_ids: tuple[int, ...],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for run in scheduler._runs.values():
        if run.session.player_id in player_ids:
            mapping[run.session.player_id] = run.session.run_id
    return mapping


def _end_open_table_stream(
    scope: InferenceStreamScope,
    scheduler: InferenceRowScheduler,
) -> None:
    controller = controller_for_scope(scope)
    if controller is not None:
        controller.end_stream(scheduler)


def _host_turn_context(
    sample_turn,
    persistence,
    *,
    seed_player_ids: int | tuple[int, ...] | None = None,
):
    host_turn, stored_turns = host_turn_at(sample_turn, HOST_TURN)
    kwargs: dict[str, object] = {
        "persistence": persistence,
        "stored_turns": stored_turns,
    }
    if seed_player_ids is not None:
        kwargs["seed_fleet_prerequisites_for"] = seed_player_ids
    ctx = export_chain_query_context(host_turn, **kwargs)
    return host_turn, ctx


def _seed_prior_turn_fleet_with_belief_sets(
    ctx,
    *,
    host_turn,
    player_id: int,
    torp_ids: tuple[int, ...],
) -> FleetSnapshotPersistenceService:
    prior_turn = host_turn.settings.turn - 1
    fleet_services = ctx.export_services["fleet"]
    persistence = fleet_services.persistence
    snapshot = persistence.get_snapshot(ctx.game_id, ctx.perspective, prior_turn)
    if snapshot is None:
        from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot

        prior_turn_obj = replace(
            host_turn,
            settings=replace(host_turn.settings, turn=prior_turn),
            game=replace(host_turn.game, turn=prior_turn),
        )
        snapshot = get_or_materialize_fleet_snapshot(
            persistence,
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
                        FleetBuildOptionSet(torp_id=torp_id, label=f"Mk {torp_id}")
                        for torp_id in torp_ids
                    ],
                ),
            ],
        ),
    ]
    persistence.put_snapshot(ctx.game_id, ctx.perspective, prior_turn, snapshot)
    return persistence


def test_fleet_persist_at_prior_turn_invalidates_scores_stream_rows(
    sample_turn,
    persistence,
    monkeypatch,
):
    """Fleet@(N-1) persist drops scores@N cache and reschedules open stream rows."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_ids,
    )
    turn_number = HOST_TURN

    fleet_persistence = ctx.export_services["fleet"].persistence
    inference_persistence = persistence
    _wire_fleet_scores_invalidation(inference_persistence, fleet_persistence, scheduler)

    for player_id in player_ids:
        inference_persistence.put_row(
            ctx.game_id,
            ctx.perspective,
            turn_number,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary=f"cached-{player_id}",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )

    def resolve_fleet_torp_resolution_for_player(
        player_id: int,
    ) -> PriorTurnFleetTorpResolution:
        return resolve_prior_turn_fleet_torp_overlay(
            turn=host_turn,
            player_id=player_id,
            load_turn=ctx.load_turn,
            export_services=ctx.export_services,
            ensure=False,
        )

    stream = iter_scores_table_inference_events(
        host_turn,
        player_ids,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        load_scoreboard_turn=ctx.load_turn,
        resolve_fleet_torp_resolution_for_player=resolve_fleet_torp_resolution_for_player,
        persistence=inference_persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()
    _wait_until(
        lambda: sum(1 for event in events if event.get("type") == "complete") >= len(player_ids)
    )
    assert (
        controller_for_scope(
            InferenceStreamScope(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn_number=turn_number,
            )
        )
        is not None
    )

    target_player_id = player_ids[0]
    before_run_id = _run_ids_for_players(scheduler, (target_player_id,)).get(target_player_id)
    assert before_run_id is None

    _seed_prior_turn_fleet_with_belief_sets(
        ctx,
        host_turn=host_turn,
        player_id=target_player_id,
        torp_ids=(4, 8),
    )

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    for player_id in player_ids:
        assert (
            inference_persistence.get_row(ctx.game_id, ctx.perspective, turn_number, player_id)
            is None
        )

    scope = InferenceStreamScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=turn_number,
    )
    _end_open_table_stream(scope, scheduler)
    thread.join(timeout=2.0)


def test_background_warm_eventually_applies_fleet_overlay(
    sample_turn,
    persistence,
    monkeypatch,
):
    """Background warm materializes fleet@(N-1) so overlay resolves with belief set."""
    player_id = 8
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_id,
    )
    prior_turn = HOST_TURN - 1

    fleet_persistence = ctx.export_services["fleet"].persistence
    fleet_persistence.delete_snapshot(ctx.game_id, ctx.perspective, prior_turn)

    pending = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )
    assert pending.input_status == "pending"
    assert pending.overlay is None

    _run_warm_synchronously(monkeypatch)
    schedule_background_prior_turn_fleet_warm(
        turn=host_turn,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        player_ids=(player_id,),
    )

    assert fleet_persistence.has_final_ledger(
        ctx.game_id,
        ctx.perspective,
        prior_turn,
        player_id,
    )

    applied = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )
    assert applied.input_status == "applied"
    assert applied.overlay is not None


def test_stream_recompute_reschedules_after_fleet_overlay_lands(
    sample_turn,
    persistence,
    monkeypatch,
):
    """First-pass pending overlay triggers reschedule when fleet@(N-1) persists."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_scheduler(monkeypatch, worker_count=1)
    player_id = sample_turn.scores[0].ownerid
    player_ids = (player_id,)
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_id,
    )

    fleet_persistence = ctx.export_services["fleet"].persistence
    prior_turn = HOST_TURN - 1
    fleet_persistence.delete_snapshot(ctx.game_id, ctx.perspective, prior_turn)

    inference_persistence = persistence
    _wire_fleet_scores_invalidation(inference_persistence, fleet_persistence, scheduler)

    scope = InferenceStreamScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=HOST_TURN,
    )

    def resolve_fleet_torp_resolution_for_player(
        resolved_player_id: int,
    ) -> PriorTurnFleetTorpResolution:
        return resolve_prior_turn_fleet_torp_overlay(
            turn=host_turn,
            player_id=resolved_player_id,
            load_turn=ctx.load_turn,
            export_services=ctx.export_services,
            ensure=False,
        )

    stream = iter_scores_table_inference_events(
        host_turn,
        player_ids,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        load_scoreboard_turn=ctx.load_turn,
        resolve_fleet_torp_resolution_for_player=resolve_fleet_torp_resolution_for_player,
        persistence=inference_persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()
    try:
        _wait_until(
            lambda: any(event.get("type") == "complete" for event in events),
            timeout_seconds=30.0,
        )

        first_complete = next(event for event in events if event.get("type") == "complete")
        first_diagnostics = first_complete.get("diagnostics")
        assert isinstance(first_diagnostics, dict)
        assert first_diagnostics.get("fleetTorpInputStatus") == "pending"

        _seed_prior_turn_fleet_with_belief_sets(
            ctx,
            host_turn=host_turn,
            player_id=player_id,
            torp_ids=(4,),
        )

        _wait_until(lambda: player_id in _run_ids_for_players(scheduler, player_ids))
        assert (
            inference_persistence.get_row(
                ctx.game_id,
                ctx.perspective,
                HOST_TURN,
                player_id,
            )
            is None
        )

        applied = resolve_prior_turn_fleet_torp_overlay(
            turn=host_turn,
            player_id=player_id,
            load_turn=ctx.load_turn,
            export_services=ctx.export_services,
            ensure=False,
        )
        assert applied.input_status == "applied"
        assert applied.overlay is not None
        assert applied.overlay.belief_set.torp_ids == frozenset({4})
    finally:
        _end_open_table_stream(scope, scheduler)
        thread.join(timeout=2.0)


def test_inference_overlay_changes_diagnostics_vs_empty_overlay(
    sample_turn,
    persistence,
):
    """Scores row inference: fleet overlay changes torp admission diagnostics."""
    from api.analytics.scores.inference import get_scores_row_inference

    player_id = sample_turn.scores[0].ownerid
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_id,
    )
    belief_torp_ids = (1, 2)
    _seed_prior_turn_fleet_with_belief_sets(
        ctx,
        host_turn=host_turn,
        player_id=player_id,
        torp_ids=belief_torp_ids,
    )

    empty_overlay = FleetTorpOverlay(belief_set=FleetLauncherBeliefSet(frozenset()))
    fleet_resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=host_turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        export_services=ctx.export_services,
        ensure=False,
    )
    assert fleet_resolution.overlay is not None

    empty_inference = get_scores_row_inference(
        host_turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        fleet_torp_overlay=empty_overlay,
        fleet_torp_input_status="applied",
    )
    belief_inference = get_scores_row_inference(
        host_turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        fleet_torp_overlay=fleet_resolution.overlay,
        fleet_torp_input_status="applied",
    )

    empty_diag = _fleet_overlay_from_diagnostics(empty_inference["diagnostics"])
    belief_diag = _fleet_overlay_from_diagnostics(belief_inference["diagnostics"])
    assert empty_diag.get("beliefSetTorpIds") == []
    assert belief_diag.get("beliefSetTorpIds") == list(belief_torp_ids)

    observation = build_inference_observation(
        score,
        host_turn,
        load_scoreboard_turn=ctx.load_turn,
    )
    torp_step = next(step for step in resolve_tier_policies() if step.id == "admit_ship_torpedoes")
    empty_torp_catalog = build_action_catalog_from_turn(
        observation,
        host_turn,
        policy_step=torp_step,
        fleet_torp_overlay=empty_overlay,
    )
    belief_torp_catalog = build_action_catalog_from_turn(
        observation,
        host_turn,
        policy_step=torp_step,
        fleet_torp_overlay=fleet_resolution.overlay,
    )
    assert empty_torp_catalog.fleet_torp_overlay_diagnostics is not None
    assert belief_torp_catalog.fleet_torp_overlay_diagnostics is not None
    assert empty_torp_catalog.fleet_torp_overlay_diagnostics.admitted_torp_ids == ()
    assert belief_torp_catalog.fleet_torp_overlay_diagnostics.admitted_torp_ids == belief_torp_ids


def test_get_scores_row_inference_emits_applied_fleet_torp_input_status(
    sample_turn,
    persistence,
):
    """Row inference diagnostics report applied when prior fleet snapshot exists."""
    from api.analytics.scores.inference import get_scores_row_inference

    player_id = sample_turn.scores[0].ownerid
    host_turn, ctx = _host_turn_context(
        sample_turn,
        persistence,
        seed_player_ids=player_id,
    )
    _seed_prior_turn_fleet_with_belief_sets(
        ctx,
        host_turn=host_turn,
        player_id=player_id,
        torp_ids=(4, 8),
    )

    inference = get_scores_row_inference(
        host_turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        fleet_torp_overlay=resolve_prior_turn_fleet_torp_overlay(
            turn=host_turn,
            player_id=player_id,
            load_turn=ctx.load_turn,
            export_services=ctx.export_services,
            ensure=False,
        ).overlay,
        fleet_torp_input_status="applied",
    )
    diagnostics = inference.get("diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("fleetTorpInputStatus") == "applied"
    assert inference.get("fleetTorpInputStatus") == "applied"
    assert inference.get("fleetTorpOverlayBeliefSetTorpIds") == [4, 8]
    fleet_overlay = diagnostics.get("fleetTorpOverlay")
    assert isinstance(fleet_overlay, dict)
    assert fleet_overlay.get("beliefSetTorpIds") == [4, 8]


def test_fleet_torp_input_status_not_applicable_on_first_turn(first_turn):
    ctx = export_chain_query_context(first_turn)
    resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=first_turn,
        player_id=8,
        load_turn=ctx.load_turn,
        query_context=ctx,
    )
    assert resolution.input_status == "not_applicable"
