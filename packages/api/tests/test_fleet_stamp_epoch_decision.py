"""Fleet persist stamps only while its job epoch is still current."""

from __future__ import annotations

import api.analytics.fleet.compute_orchestration as fleet_persist
import pytest
from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import STAMP_CURRENT_EVIDENCE_MARK
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.registry import build_compute_registry
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.exceptions import DiscardedWorkRefused
from api.services.off_mode_bump import discard_bumped_player_work

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import (
    context_at_turn,
    player_ledger,
    store_generation,
    write_evidence_mark,
)


def test_persist_that_passed_the_epoch_check_does_not_store_the_new_mark(
    sample_turn,
    monkeypatch,
):
    """Move the mark after the fast epoch check. The put leaves the file in place."""
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=40,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 4, ship_id=40)
    before = persisted_fleet_ledger_to_json(
        persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    )
    real_merge = fleet_persist.observation_merge_generation
    moved = False

    def move_mark_then_merge(*args, **kwargs):
        nonlocal moved
        moved = True
        persistence.invalidate_player_ledgers_from_turn(
            ctx.game_id,
            ctx.perspective,
            40,
            player_id,
            durable=True,
        )
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(fleet_persist, "observation_merge_generation", move_mark_then_merge)
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )

    with pytest.raises(DiscardedWorkRefused):
        FleetPersistencePolicy().persist(
            ctx,
            scope,
            {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
        )

    assert moved
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None
    assert persisted_fleet_ledger_to_json(stored) == before
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 5
    )


def test_put_without_a_job_epoch_stamps_the_mark_after_a_durable_bump(sample_turn):
    """A caller that is not an in-flight fleet job still stamps the current mark."""
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=40,
    )
    persistence.invalidate_player_ledgers_from_turn(
        ctx.game_id,
        ctx.perspective,
        40,
        player_id,
        durable=True,
    )

    persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        40,
        player_id,
        player_ledger(player_id, ship_id=40),
        evidence_generation=STAMP_CURRENT_EVIDENCE_MARK,
    )

    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 5


def _drive_epoch_lock_refusal_during_persist(sample_turn, monkeypatch, *, shell: bool):
    """Running fleet persist loses the generation lock after the fast epoch check.

    ``shell`` is a running shell turn: the bump leaves it unflagged and a wake
    attaches before the put refuses. Otherwise the bump flags the running turn.
    """
    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=40,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 4, ship_id=40)
    before = persisted_fleet_ledger_to_json(
        persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    )
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((FLEET_REGISTRATION,)),
    )
    epoch = persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        generation_at_submit=epoch,
        bundle=OrchestrationBundle.from_context(ctx),
        submission_open=SubmissionOpen(open_turn=40),
    )
    orchestrator.nodes[scope] = node
    real_merge = fleet_persist.observation_merge_generation
    shell_turns = frozenset({40}) if shell else frozenset()

    def move_mark_then_merge(*args, **kwargs):
        discard_bumped_player_work(
            orchestrator,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            player_id=player_id,
            shell_turns=shell_turns,
            live_turns=frozenset(),
        )
        persistence.invalidate_player_ledgers_from_turn(
            ctx.game_id,
            ctx.perspective,
            40,
            player_id,
            durable=True,
        )
        if shell:
            assert fleet_persist.wake_fleet_scope(scope, orchestrator=orchestrator) is True
            assert node.state == "running"
            assert node.discard_without_stamp is False
            assert len(node.waiters) == 1
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(fleet_persist, "observation_merge_generation", move_mark_then_merge)
    complete_running_pool_step(
        orchestrator,
        scope,
        result_wire={
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": epoch,
        },
    )

    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None
    assert persisted_fleet_ledger_to_json(stored) == before
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 5
    )
    assert orchestrator.nodes[scope] is node
    return orchestrator, node


def test_shell_inside_persist_is_requeued_when_the_epoch_lock_refuses(sample_turn, monkeypatch):
    """A shell inside persist loses the epoch race and the same node is ready again."""
    orchestrator, node = _drive_epoch_lock_refusal_during_persist(
        sample_turn,
        monkeypatch,
        shell=True,
    )

    assert node.state == "ready"
    assert node.discard_without_stamp is False
    assert node.error is None
    assert node.generation_at_submit is None
    assert node.scope in orchestrator._ready_queue
    assert orchestrator.metrics.epoch_discards == 1
    assert len(node.waiters) == 1
    assert node.waiters[0]._node is node
    assert node.waiters[0].error is None


def test_discard_flagged_persist_refusal_is_not_requeued(sample_turn, monkeypatch):
    """Off-screen work flagged during persist fails and is not retried."""
    orchestrator, node = _drive_epoch_lock_refusal_during_persist(
        sample_turn,
        monkeypatch,
        shell=False,
    )

    assert node.state == "failed"
    assert node.discard_without_stamp is True
    assert isinstance(node.error, DiscardedWorkRefused)
    assert node.generation_at_submit is not None
    assert node.scope not in orchestrator._ready_queue
    assert orchestrator.metrics.epoch_discards == 0
    assert node.waiters == []
