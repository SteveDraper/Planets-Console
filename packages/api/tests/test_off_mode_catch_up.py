"""Off-mode catch-up wiring: submitted scopes, stamp versus bump, refused late persist."""

from __future__ import annotations

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
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
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
from api.services.off_mode_bump import discard_bumped_player_work
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import (
    context_at_turn,
    install_submission_root,
    open_turn_fields,
    planned_scope_keys,
    player_ledger,
    store_generation,
    write_evidence_mark,
)


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

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    stamped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert stamped == FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None
    assert root.open_turn_consumed is True
    assert orchestrator.nodes[offscreen].state == "running"
    assert orchestrator.nodes[offscreen].discard_without_stamp is False
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

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

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 4
    assert fleet.open_turn_consumed is True
    assert orchestrator.nodes[scores_scope].open_turn_consumed is True

    fresh = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 42)
    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 41, player_id)
    assert fresh.open_turn_consumed is False


def test_root_bump_wakes_the_shell_chosen_before_consume(
    sample_turn,
    monkeypatch,
):
    """A bump of the open root still wakes that shell after the claim consumes it."""
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
    store_generation(persistence, ctx.game_id, ctx.perspective, 4, player_id, 2, ship_id=4)
    store_generation(persistence, ctx.game_id, ctx.perspective, 5, player_id, 2, ship_id=5)
    store_generation(persistence, ctx.game_id, ctx.perspective, 6, player_id, 2, ship_id=6)
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 4)
    root.submission_open = SubmissionOpen(
        open_turn=root.submission_open.open_turn,
        backfill_earlier_turns=True,
    )
    woken: list[int] = []

    def spy_reschedule(_scope, _player_id):
        return False

    def spy_wake(scope, **_kwargs):
        woken.append(scope.turn)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        spy_wake,
    )
    live_scope = FleetTableStreamScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=5,
    )

    class _LiveStream:
        stream_token = "turn-5"

    get_fleet_table_stream_registry().attach(live_scope, _LiveStream())
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )
    try:
        invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 4, player_id)
    finally:
        reset_fleet_table_stream_registry_for_tests()

    assert root.open_turn_consumed is True
    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 3
    assert 4 in woken
    assert 5 in woken
    assert 6 not in woken
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

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)

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


def test_bump_drops_offscreen_hops_and_refuses_an_executing_step():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=39,
        player_id=7,
    )
    running = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=39,
        player_id=7,
    )
    shell = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=40,
        player_id=7,
    )
    orchestrator.nodes[ready] = ComputeNodeRun(
        scope=ready, dependency_scopes=(), state="ready", submission_open=SubmissionOpen()
    )
    orchestrator.nodes[running] = ComputeNodeRun(
        scope=running,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(),
    )
    orchestrator.nodes[shell] = ComputeNodeRun(
        scope=shell,
        dependency_scopes=(),
        state="waiting_deps",
        submission_open=SubmissionOpen(),
    )
    orchestrator._ready_queue.append(ready)

    discard_bumped_player_work(
        orchestrator,
        game_id=1,
        perspective=1,
        player_id=7,
        shell_turns=frozenset({40}),
        live_turns=frozenset(),
    )

    assert orchestrator.nodes[ready].state == "failed"
    assert ready not in orchestrator._ready_queue
    assert orchestrator.nodes[running].state == "running"
    assert orchestrator.nodes[running].discard_without_stamp is True
    assert orchestrator.nodes[shell].state == "failed"

    with orchestrator._condition:
        abandoned = orchestrator._abandon_persist_if_not_running_or_stale(
            orchestrator.nodes[running]
        )
    assert abandoned is True
    assert orchestrator.nodes[running].state == "failed"


def test_executing_offscreen_work_is_flagged_before_the_epoch_bump(sample_turn, monkeypatch):
    """Both bump paths flag off-screen work before the epoch or the mark moves.

    The flag and the failed hop are already applied when
    ``invalidate_player_ledgers_from_turn`` is entered. Wake runs after that
    call returns. A shell step that is already running stays running.
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
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    phase = {"invalidate_returned": False, "wake_before": False}
    woken: list[int] = []

    def note_wake(turn: int) -> None:
        if not phase["invalidate_returned"]:
            phase["wake_before"] = True
        woken.append(turn)

    def spy_reschedule(scope, _player_id):
        note_wake(scope.turn_number)
        return False

    def spy_wake(scope, **_kwargs):
        note_wake(scope.turn)
        return True

    def spy_scores(scope, _player_id):
        note_wake(scope.turn_number)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        spy_wake,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        spy_scores,
    )
    original_invalidate = persistence.invalidate_player_ledgers_from_turn

    def drive(call) -> None:
        orchestrator = ComputeOrchestrator(compute_registry={})
        shell = ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        )
        running = ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=38,
            player_id=player_id,
        )
        ready = ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=37,
            player_id=player_id,
        )
        shell_node = install_submission_root(
            orchestrator, ctx.game_id, ctx.perspective, player_id, 40
        )
        shell_node.state = "running"
        orchestrator.nodes[running] = ComputeNodeRun(
            scope=running,
            dependency_scopes=(),
            state="running",
            submission_open=SubmissionOpen(),
        )
        orchestrator.nodes[ready] = ComputeNodeRun(
            scope=ready,
            dependency_scopes=(),
            state="ready",
            submission_open=SubmissionOpen(),
        )
        orchestrator._ready_queue.append(ready)
        invalidation = InferenceInvalidationService(
            InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            fleet_persistence=persistence,
            orchestrator=lambda: orchestrator,
        )
        epoch_before = persistence.player_invalidation_generation(
            ctx.game_id, ctx.perspective, player_id
        )
        mark_before = persistence.evidence_mark(
            ctx.game_id, ctx.perspective, player_id
        ).evidence_generation
        seen: dict[str, object] = {}
        phase["invalidate_returned"] = False
        phase["wake_before"] = False
        woken.clear()

        def spy_invalidate(*args, **kwargs):
            seen["flagged"] = orchestrator.nodes[running].discard_without_stamp
            seen["ready_state"] = orchestrator.nodes[ready].state
            seen["ready_queued"] = ready in orchestrator._ready_queue
            seen["shell_flagged"] = orchestrator.nodes[shell].discard_without_stamp
            seen["shell_state"] = orchestrator.nodes[shell].state
            seen["epoch"] = persistence.player_invalidation_generation(
                ctx.game_id, ctx.perspective, player_id
            )
            seen["mark"] = persistence.evidence_mark(
                ctx.game_id, ctx.perspective, player_id
            ).evidence_generation
            result = original_invalidate(*args, **kwargs)
            phase["invalidate_returned"] = True
            return result

        persistence.invalidate_player_ledgers_from_turn = spy_invalidate
        try:
            call(invalidation)
        finally:
            persistence.invalidate_player_ledgers_from_turn = original_invalidate

        assert seen["flagged"] is True
        assert seen["ready_state"] == "failed"
        assert seen["ready_queued"] is False
        assert seen["shell_flagged"] is False
        assert seen["shell_state"] == "running"
        assert seen["epoch"] == epoch_before
        assert seen["mark"] == mark_before
        assert phase["wake_before"] is False
        assert 40 in woken
        assert (
            persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
            == epoch_before + 1
        )
        assert (
            persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation
            == mark_before + 1
        )
        assert orchestrator.nodes[running].state == "running"
        assert orchestrator.nodes[shell].state == "running"

    def persist_scores(invalidation: InferenceInvalidationService) -> None:
        invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 39, player_id)

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
    assert orchestrator.nodes[running].discard_without_stamp is False
    assert (
        persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
        == epoch_before + 1
    )
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 3
    )


def test_bump_recomputes_shell_and_live_turns_and_leaves_other_later_turns_on_disk(
    sample_turn,
    monkeypatch,
):
    """A durable bump wakes the shell and any later turn that already has a live stream.

    A later turn with no live stream stays on disk.
    """
    host, ctx = context_at_turn(sample_turn, 6)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    store_generation(persistence, ctx.game_id, ctx.perspective, 4, player_id, 1, ship_id=4)
    store_generation(persistence, ctx.game_id, ctx.perspective, 5, player_id, 1, ship_id=5)
    store_generation(persistence, ctx.game_id, ctx.perspective, 6, player_id, 1, ship_id=6)
    orchestrator = ComputeOrchestrator(compute_registry={})
    install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 4)
    rescheduled: list[int] = []
    woken: list[int] = []

    def spy_reschedule(scope, _player_id):
        rescheduled.append(scope.turn_number)
        return False

    def spy_wake(scope, **_kwargs):
        woken.append(scope.turn)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        spy_wake,
    )
    live_scope = FleetTableStreamScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=5,
    )

    class _LiveStream:
        stream_token = "turn-5"

    get_fleet_table_stream_registry().attach(live_scope, _LiveStream())
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )
    try:
        invalidation.on_inference_evidence_updated(
            ctx.game_id,
            ctx.perspective,
            4,
            player_id,
            durable=True,
        )
    finally:
        reset_fleet_table_stream_registry_for_tests()

    assert 4 in rescheduled or 4 in woken
    assert 5 in rescheduled or 5 in woken
    assert 6 not in rescheduled
    assert 6 not in woken
    live = persistence.get_ledger(ctx.game_id, ctx.perspective, 5, player_id)
    untouched = persistence.get_ledger(ctx.game_id, ctx.perspective, 6, player_id)
    assert live is not None and live.ledger.records[0].record_id == "ship-5"
    assert untouched is not None and untouched.ledger.records[0].record_id == "ship-6"


def test_limited_bump_reschedules_scores_rows_from_the_same_live_scan(
    sample_turn,
    monkeypatch,
):
    """A limited bump walks live streams once and wakes scores only on that scan.

    A fleet-only stream and a scores stream before the host turn do not
    reschedule a scores row.
    """
    host, ctx = context_at_turn(sample_turn, 6)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    store_generation(persistence, ctx.game_id, ctx.perspective, 4, player_id, 1, ship_id=4)
    store_generation(persistence, ctx.game_id, ctx.perspective, 5, player_id, 1, ship_id=5)
    store_generation(persistence, ctx.game_id, ctx.perspective, 6, player_id, 1, ship_id=6)
    orchestrator = ComputeOrchestrator(compute_registry={})
    install_submission_root(orchestrator, ctx.game_id, ctx.perspective, player_id, 4)
    fleet_turns: list[int] = []
    scores_turns: list[int] = []
    list_calls = {"fleet": 0, "scores": 0}

    def spy_fleet(scope, _player_id):
        fleet_turns.append(scope.turn_number)
        return False

    def spy_scores(scope, _player_id):
        scores_turns.append(scope.turn_number)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_fleet,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        lambda _scope, **_kwargs: True,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        spy_scores,
    )
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    get_fleet_table_stream_registry().attach(
        FleetTableStreamScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn_number=5,
        ),
        object(),
    )
    scores_registry = get_inference_table_stream_registry()
    scores_registry.attach(
        InferenceStreamScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn_number=3,
        ),
        object(),
    )
    scores_registry.attach(
        InferenceStreamScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn_number=6,
        ),
        object(),
    )
    fleet_registry = get_fleet_table_stream_registry()
    fleet_list = fleet_registry.list_active_scopes
    scores_list = scores_registry.list_active_scopes

    def counting_fleet():
        list_calls["fleet"] += 1
        return fleet_list()

    def counting_scores():
        list_calls["scores"] += 1
        return scores_list()

    monkeypatch.setattr(fleet_registry, "list_active_scopes", counting_fleet)
    monkeypatch.setattr(scores_registry, "list_active_scopes", counting_scores)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )
    try:
        invalidation.on_inference_evidence_updated(
            ctx.game_id,
            ctx.perspective,
            4,
            player_id,
            durable=True,
        )
    finally:
        reset_fleet_table_stream_registry_for_tests()
        reset_inference_table_stream_registry_for_tests()

    assert fleet_turns == [4, 5, 6]
    assert scores_turns == [6]
    assert list_calls == {"fleet": 1, "scores": 1}


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
