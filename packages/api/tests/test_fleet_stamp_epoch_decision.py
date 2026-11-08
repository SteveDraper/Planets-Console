"""Fleet persist stamps only while its job epoch is still current."""

from __future__ import annotations

import api.analytics.fleet.compute_orchestration as fleet_persist
import pytest
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import STAMP_CURRENT_EVIDENCE_MARK
from api.compute.scope import ComputeScope
from api.exceptions import DiscardedWorkRefused

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
