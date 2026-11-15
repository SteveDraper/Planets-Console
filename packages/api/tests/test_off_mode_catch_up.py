"""Off-mode catch-up wiring: submitted scopes, stamp versus bump, refused late persist."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.homeworld_locator.constants import ANALYTIC_ID as HOMEWORLD_ANALYTIC_ID
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG as HOMEWORLD_EXPORT_CATALOG
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.running_step import RunningStepDisposition
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.errors import ValidationError
from api.exceptions import DiscardedWorkRefused
from api.serialization.backfill_earlier_turns import (
    backfill_earlier_turns_document,
    backfill_earlier_turns_store_key,
)
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import (
    FLEET_SCORES_REGISTRY,
    context_at_turn,
    install_submission_root,
    open_turn_fields,
    planned_scope_keys,
    player_ledger,
    store_generation,
    write_evidence_mark,
)
from tests.on_walk_live_helpers import LiveStream, attach_stream
from tests.walk_band_helpers import no_live_streams


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


def _close_live_streams() -> None:
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


def _invalidation(persistence, orchestrator: ComputeOrchestrator) -> InferenceInvalidationService:
    return InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )


def _record_fleet_scope_wakes(monkeypatch) -> list[int]:
    """The turns of fleet scopes the bump wakes without a live row; a durable bump wakes none."""
    woken: list[int] = []
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        lambda scope, _player_id: woken.append(scope.turn_number) or False,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        lambda scope, **_kwargs: woken.append(scope.turn) or True,
    )
    return woken


def _open_fleet_row(ctx, player_id: int, turn: int) -> LiveStream:
    return attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, turn),
        None,
        ctx,
        [player_id],
    )


def _open_scoreboard_row(ctx, player_id: int, turn: int) -> LiveStream:
    return attach_stream(
        get_inference_table_stream_registry(),
        InferenceStreamScope(ctx.game_id, ctx.perspective, turn),
        None,
        ctx,
        [player_id],
    )


def _put_node(
    orchestrator: ComputeOrchestrator, ctx, player_id: int, analytic_id: str, turn: int, state
) -> ComputeScope:
    scope = ComputeScope(
        analytic_id=analytic_id,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope, dependency_scopes=(), state=state, submission_open=SubmissionOpen()
    )
    if state == "ready":
        orchestrator._ready_queue.append(scope)
    return scope


def test_stale_open_refreshes_back_through_the_mark_and_skips_scoreboard(sample_turn):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    write_evidence_mark(
        services.persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=2,
        applies_from=38,
    )
    store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 38, player_id, 2, ship_id=38
    )
    store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 39, player_id, 1, ship_id=39
    )
    store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=41
    )

    planned = planned_scope_keys(ctx, FLEET_ANALYTIC_ID, 40, player_id)

    assert planned == {(FLEET_ANALYTIC_ID, 40), (FLEET_ANALYTIC_ID, 39)}
    assert (SCORES_ANALYTIC_ID, 39) not in planned
    assert (FLEET_ANALYTIC_ID, 41) not in planned
    assert (FLEET_ANALYTIC_ID, 38) not in planned


def test_absent_mark_does_not_walk_backward(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    player_id = first_player_id(host)

    planned = planned_scope_keys(ctx, FLEET_ANALYTIC_ID, 10, player_id)

    assert planned == {(FLEET_ANALYTIC_ID, 10)}


def test_later_turn_uses_matching_fleet_and_does_not_invent_earlier_turns(sample_turn):
    host, ctx = context_at_turn(sample_turn, 11)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    write_evidence_mark(
        services.persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=1,
        applies_from=10,
    )
    store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 10, player_id, 1, ship_id=10
    )

    planned = planned_scope_keys(ctx, SCORES_ANALYTIC_ID, 11, player_id)

    assert (FLEET_ANALYTIC_ID, 9) not in planned
    assert (FLEET_ANALYTIC_ID, 10) not in planned
    assert (SCORES_ANALYTIC_ID, 10) not in planned
    assert (SCORES_ANALYTIC_ID, 11) in planned


def test_homeworld_open_does_not_start_the_catch_up(sample_turn):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    dependencies = HOMEWORLD_EXPORT_CATALOG.applicable_ensure_dependencies(
        ctx,
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )

    assert dependencies
    assert all(dependency.analytic_id == HOMEWORLD_ANALYTIC_ID for dependency in dependencies)


def test_catch_up_hop_stamps_and_open_turn_keeps_its_generation(sample_turn):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=38,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    policy = FleetPersistencePolicy()

    hop_callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=39,
            player_id=player_id,
        ),
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **open_turn_fields(40, 39),
        },
    )
    assert hop_callback is None
    untouched = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert untouched is not None
    assert untouched.evidence_generation == 1
    assert untouched.ledger.records[0].record_id == "ship-40"

    open_callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **open_turn_fields(40, 40),
        },
    )
    assert open_callback is not None

    hop = persistence.get_ledger(ctx.game_id, ctx.perspective, 39, player_id)
    opened = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert hop is not None and hop.evidence_generation == 4
    assert opened is not None and opened.evidence_generation == 1
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 4
    )


def test_opening_turn_does_not_rewrite_a_later_turn(sample_turn):
    host, ctx = context_at_turn(sample_turn, 41)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=2,
        applies_from=40,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=411)
    policy = FleetPersistencePolicy()
    callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **open_turn_fields(40, 40),
        },
    )
    assert callback is not None
    callback()

    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
    assert later is not None
    assert later.ledger.records[0].record_id == "ship-411"


def test_catch_up_scoreboard_stamps_and_new_information_bumps(sample_turn):
    _host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(sample_turn)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=40,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 3, ship_id=40)
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 40)
    offscreen = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=39,
        player_id=player_id,
    )
    orchestrator.nodes[offscreen] = ComputeNodeRun(
        scope=offscreen,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(),
    )
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id, on_walk=False)

    stamped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert stamped == FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None
    assert root.open_turn_consumed is True
    assert orchestrator.nodes[offscreen].state == "running"
    assert orchestrator.nodes[offscreen].running_step is RunningStepDisposition.CONTINUE
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id, on_walk=False)

    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 4
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None


def test_scores_root_backfill_wins_and_a_later_turn_does_not_consume(sample_turn):
    """The scores root's carried backfill classifies the persist.

    Fleet carrying backfill off would stamp. Scores carrying it on bumps, and
    both roots are consumed. A later host turn is not that root, so it leaves
    a fresh open unconsumed.
    """
    _host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(sample_turn)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=40,
    )
    orchestrator = ComputeOrchestrator(compute_registry={})
    fleet = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 40)
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )
    orchestrator.nodes[scores_scope] = ComputeNodeRun(
        scope=scores_scope,
        dependency_scopes=(),
        state="waiting_deps",
        submission_open=SubmissionOpen(open_turn=40, backfill_earlier_turns=True),
    )
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id, on_walk=False)

    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 4
    assert fleet.open_turn_consumed is True
    assert orchestrator.nodes[scores_scope].open_turn_consumed is True

    fresh = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 42)
    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 41, player_id, on_walk=False)
    assert fresh.open_turn_consumed is False


def test_root_bump_consumes_the_root_and_wakes_live_rows_not_the_root(sample_turn, monkeypatch):
    """The claim still consumes the open root; the wake follows live rows, not roots."""
    host, ctx = context_at_turn(sample_turn, 6)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=2,
        applies_from=4,
    )
    for turn in (4, 5, 6):
        store_generation(
            persistence, ctx.game_id, ctx.perspective, turn, player_id, 2, ship_id=turn
        )
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 4)
    root.submission_open = SubmissionOpen(
        open_turn=root.submission_open.open_turn,
        backfill_earlier_turns=True,
    )
    fleet_scope_wakes = _record_fleet_scope_wakes(monkeypatch)
    row = _open_fleet_row(ctx, player_id, 5)
    invalidation = _invalidation(persistence, orchestrator)

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 4, player_id, on_walk=False)

    assert root.open_turn_consumed is True
    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 3
    assert row.rescheduled_player_ids == [player_id]
    assert fleet_scope_wakes == []
    untouched = persistence.get_ledger(ctx.game_id, ctx.perspective, 6, player_id)
    assert untouched is not None and untouched.ledger.records[0].record_id == "ship-6"


def test_first_scoreboard_persist_sets_generation_one(sample_turn):
    _host, ctx = context_at_turn(sample_turn, 10)
    player_id = first_player_id(sample_turn)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id, on_walk=False)

    mark = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert mark == FleetEvidenceMark(evidence_generation=1, applies_from_turn=10)
    persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        10,
        player_id,
        player_ledger(player_id, ship_id=10),
    )
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 10, player_id)
    assert stored is not None and stored.evidence_generation == 1


def test_late_persist_is_refused(sample_turn):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    persistence.bump_player_and_turn_invalidations(
        ctx.game_id,
        ctx.perspective,
        player_id,
        (40,),
    )
    policy = FleetPersistencePolicy()

    try:
        policy.persist(
            ctx,
            ComputeScope(
                analytic_id=FLEET_ANALYTIC_ID,
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=40,
                player_id=player_id,
            ),
            {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
        )
    except DiscardedWorkRefused:
        refused = True
    else:
        refused = False

    assert refused
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 1
    assert stored.ledger.records[0].record_id == "ship-40"


def test_persist_requires_the_job_epoch(sample_turn):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    policy = FleetPersistencePolicy()
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )

    for wire in (
        {"fleetPersistLeg": "observation"},
        {"fleetPersistLeg": "observation", "playerInvalidationGeneration": True},
    ):
        try:
            policy.persist(ctx, scope, wire)
        except ValidationError as exc:
            assert "playerInvalidationGeneration" in str(exc)
        else:
            raise AssertionError("persist without an integer epoch must be rejected")

    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 1
    assert stored.ledger.records[0].record_id == "ship-40"


def _other_thread_can_take(orchestrator: ComputeOrchestrator) -> bool:
    """Whether a second thread could take the orchestrator lock right now."""
    taken: list[bool] = []

    def probe() -> None:
        acquired = orchestrator._condition.acquire(blocking=False)
        if acquired:
            orchestrator._condition.release()
        taken.append(acquired)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return taken[0]


def test_the_bump_settles_then_publishes_in_one_lock_hold_then_wakes(sample_turn, monkeypatch):
    """Both durable entry points settle, publish the mark and epoch, then wake.

    When ``invalidate_player_ledgers_from_turn`` is entered, the settle has
    aborted the off-screen work and kept the running off-walk node on the
    watched live-row turn, the epoch and mark have not moved, and the
    orchestrator lock is still held, so no plan can register in between.
    The live row is rescheduled only after that call returns.
    """
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=39,
    )
    _record_fleet_scope_wakes(monkeypatch)
    original_invalidate = persistence.invalidate_player_ledgers_from_turn

    def drive(call) -> None:
        # The bump drains what its settle queued, so the orchestrator needs the
        # real registrations; its pool has no workers, so nothing runs.
        orchestrator = ComputeOrchestrator(
            compute_registry=FLEET_SCORES_REGISTRY,
            worker_pool=reset_compute_worker_pool_for_tests(worker_count=0),
        )
        row_scope = install_submission_root(
            orchestrator, ctx.game_id, ctx.perspective, player_id, 40
        ).scope
        orchestrator.nodes[row_scope].state = "running"
        running = _put_node(orchestrator, ctx, player_id, SCORES_ANALYTIC_ID, 38, "running")
        ready = _put_node(orchestrator, ctx, player_id, FLEET_ANALYTIC_ID, 37, "ready")
        row = _open_fleet_row(ctx, player_id, 40)
        order: list[str] = []
        monkeypatch.setattr(
            row, "reschedule_player", lambda _player_id: order.append("reschedule") or True
        )
        epoch_before = persistence.player_invalidation_generation(
            ctx.game_id, ctx.perspective, player_id
        )
        mark_before = persistence.evidence_mark(
            ctx.game_id, ctx.perspective, player_id
        ).evidence_generation
        seen: dict[str, object] = {}

        def spy_invalidate(*args, **kwargs):
            seen["running"] = orchestrator.nodes[running].state
            seen["ready"] = orchestrator.nodes[ready].state
            seen["ready_queued"] = ready in orchestrator._ready_queue
            seen["row"] = orchestrator.nodes[row_scope].state
            seen["epoch"] = persistence.player_invalidation_generation(
                ctx.game_id, ctx.perspective, player_id
            )
            seen["mark"] = persistence.evidence_mark(
                ctx.game_id, ctx.perspective, player_id
            ).evidence_generation
            seen["lock_held"] = not _other_thread_can_take(orchestrator)
            result = original_invalidate(*args, **kwargs)
            order.append("published")
            return result

        persistence.invalidate_player_ledgers_from_turn = spy_invalidate
        try:
            call(_invalidation(persistence, orchestrator))
        finally:
            persistence.invalidate_player_ledgers_from_turn = original_invalidate
            _close_live_streams()

        assert seen == {
            "running": "failed",
            "ready": "failed",
            "ready_queued": False,
            "row": "running",
            "epoch": epoch_before,
            "mark": mark_before,
            "lock_held": True,
        }
        assert isinstance(orchestrator.nodes[running].error, ComputeScopeAbortedError)
        assert orchestrator.nodes[row_scope].running_step is RunningStepDisposition.CONTINUE
        assert order == ["published", "reschedule"]
        assert (
            persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
            == epoch_before + 1
        )
        assert (
            persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation
            == mark_before + 1
        )

    def persist_scores(invalidation: InferenceInvalidationService) -> None:
        invalidation.on_scores_row_persisted(
            ctx.game_id, ctx.perspective, 39, player_id, on_walk=False
        )

    def update_evidence(invalidation: InferenceInvalidationService) -> None:
        invalidation.on_inference_evidence_updated(
            ctx.game_id,
            ctx.perspective,
            39,
            player_id,
            durable=True,
        )

    drive(persist_scores)
    drive(update_evidence)


def test_held_admission_leaves_executing_work_for_epoch_retry(sample_turn, monkeypatch):
    """Held admission bumps the epoch and leaves an executing node running."""
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=40,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        lambda _scope, _player_id: False,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        lambda _scope, **_kwargs: True,
    )
    orchestrator = ComputeOrchestrator(compute_registry={})
    running = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=39,
        player_id=player_id,
    )
    orchestrator.nodes[running] = ComputeNodeRun(
        scope=running,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(),
    )
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )
    epoch_before = persistence.player_invalidation_generation(
        ctx.game_id, ctx.perspective, player_id
    )

    invalidation.on_inference_evidence_updated(
        ctx.game_id,
        ctx.perspective,
        40,
        player_id,
        durable=False,
    )

    assert orchestrator.nodes[running].state == "running"
    assert orchestrator.nodes[running].running_step is RunningStepDisposition.CONTINUE
    assert (
        persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
        == epoch_before + 1
    )
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 3
    )


@pytest.mark.parametrize("backfill_enabled", [False, True])
def test_a_durable_bump_wakes_live_rows_from_the_host_turn_and_leaves_other_turns_on_disk(
    sample_turn, monkeypatch, backfill_enabled
):
    """Under either setting, only the player's live rows at the host turn and later wake.

    A submission root with no live row, a known later turn with no live row,
    and a live row below the host turn whose work the bump did not stop are
    not woken, and their ledgers stay at the old generation.
    """
    host, ctx = context_at_turn(sample_turn, 6)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    for turn in (4, 5, 6):
        store_generation(
            persistence, ctx.game_id, ctx.perspective, turn, player_id, 1, ship_id=turn
        )
    orchestrator = ComputeOrchestrator(compute_registry={})
    install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 4)
    fleet_scope_wakes = _record_fleet_scope_wakes(monkeypatch)
    fleet_row = _open_fleet_row(ctx, player_id, 5)
    early_scoreboard = _open_scoreboard_row(ctx, player_id, 3)
    later_scoreboard = _open_scoreboard_row(ctx, player_id, 6)

    _invalidation(persistence, orchestrator).on_inference_evidence_updated(
        ctx.game_id,
        ctx.perspective,
        4,
        player_id,
        durable=True,
        backfill_earlier_turns=backfill_enabled,
    )

    assert fleet_row.rescheduled_player_ids == [player_id]
    assert later_scoreboard.rescheduled_player_ids == [player_id]
    assert early_scoreboard.rescheduled_player_ids == []
    assert fleet_scope_wakes == []
    for turn in (5, 6):
        stored = persistence.get_ledger(ctx.game_id, ctx.perspective, turn, player_id)
        assert stored is not None and stored.evidence_generation == 1
        assert stored.ledger.records[0].record_id == f"ship-{turn}"


def test_backfill_on_keeps_the_final_prior_dependency(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    services.persistence._storage.put(
        backfill_earlier_turns_store_key(ctx.game_id),
        backfill_earlier_turns_document(True),
    )

    planned = planned_scope_keys(ctx, FLEET_ANALYTIC_ID, 10, player_id)

    assert (FLEET_ANALYTIC_ID, 9) in planned


def test_catch_up_hop_finalization_does_not_read_the_scoreboard(sample_turn, monkeypatch):
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)

    def fail_scoreboard(*_args, **_kwargs):
        raise AssertionError("catch-up hop read the stored scoreboard")

    monkeypatch.setattr(
        "api.analytics.fleet.approximate_fleet.terminal_fleet_ledger",
        fail_scoreboard,
    )
    policy = FleetPersistencePolicy()
    callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=39,
            player_id=player_id,
        ),
        {
            "fleetPersistLeg": "finalization",
            "persistedLedgerWire": persisted_fleet_ledger_to_json(
                player_ledger(player_id, ship_id=39)
            ),
            "playerInvalidationGeneration": 0,
            **open_turn_fields(40, 39),
        },
    )

    assert callback is None
