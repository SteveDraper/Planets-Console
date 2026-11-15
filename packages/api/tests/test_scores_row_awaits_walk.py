"""A stored scoreboard row stands in for its walk only while its prior fleet is ensure-final.

With **Backfill earlier turns** on, the walk is what makes a row's prior fleet
ensure-final, so a row whose prior is not ensure-final under the current mark
schedules rather than painting its stored row. With the setting off, a stored
row stays cached-complete.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.types import FleetMaterializationProvenance
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ScheduleRowAdmission,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.prior_fleet_walk import row_awaits_its_walk
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn, player_ledger, write_evidence_mark
from tests.scores_exports_helpers import inference_target_player_id

HOST_TURN = 40
PRIOR_TURN = HOST_TURN - 1
MARK_GENERATION = 2


def stored_complete_row() -> PersistedInferenceRow:
    return PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="stored before the bump",
        solution_count=0,
        is_complete=True,
        solutions=[],
    )


def put_ensure_final_prior(ctx, player_id: int, *, generation: int) -> None:
    """An ensure-final fleet ledger at the prior turn, stamped ``generation``."""
    ensure_final = replace(
        player_ledger(player_id, ship_id=PRIOR_TURN),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True, prior_ledger_at_n_minus_1=True
        ),
    )
    ctx.export_services[FLEET_ANALYTIC_ID].persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        PRIOR_TURN,
        player_id,
        ensure_final,
        evidence_generation=generation,
    )


@pytest.fixture
def row(sample_turn):
    """A host turn whose player has a marked fleet chain and nothing stored at the prior."""
    host, ctx = context_at_turn(sample_turn, HOST_TURN)
    player_id = inference_target_player_id(host)
    write_evidence_mark(
        ctx.export_services[FLEET_ANALYTIC_ID].persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=MARK_GENERATION,
        applies_from=PRIOR_TURN,
    )
    return host, ctx, player_id


def _awaits(host, ctx, player_id: int) -> bool:
    return row_awaits_its_walk(
        ctx, host, game_id=ctx.game_id, perspective=ctx.perspective, player_id=player_id
    )


@pytest.mark.parametrize("backfill_enabled", [False, True])
def test_a_row_whose_prior_is_ensure_final_does_not_await_its_walk(row, backfill_enabled):
    host, ctx, player_id = row
    if backfill_enabled:
        enable_backfill_earlier_turns(ctx)
    put_ensure_final_prior(ctx, player_id, generation=MARK_GENERATION)

    assert _awaits(host, ctx, player_id) is False


@pytest.mark.parametrize(
    ("prior_generation", "awaits"),
    [(None, True), (MARK_GENERATION - 1, True), (MARK_GENERATION, False)],
    ids=["missing prior", "prior behind the mark", "ensure-final prior"],
)
def test_with_the_setting_on_a_row_awaits_its_walk_until_its_prior_is_ensure_final(
    row, prior_generation, awaits
):
    host, ctx, player_id = row
    enable_backfill_earlier_turns(ctx)
    if prior_generation is not None:
        put_ensure_final_prior(ctx, player_id, generation=prior_generation)

    assert _awaits(host, ctx, player_id) is awaits


def test_with_the_setting_off_a_row_never_awaits_a_walk(row):
    host, ctx, player_id = row

    assert _awaits(host, ctx, player_id) is False


def test_a_row_at_the_ensure_floor_has_no_prior_to_wait_for(sample_turn):
    host, ctx = context_at_turn(sample_turn, HOST_TURN)
    enable_backfill_earlier_turns(ctx)
    floor = accelerated_ensure_floor(host.settings, HOST_TURN)
    at_floor = replace(host, settings=replace(host.settings, turn=floor))

    assert _awaits(at_floor, ctx, inference_target_player_id(host)) is False


def test_a_row_with_no_query_context_does_not_await_a_walk(row):
    host, _ctx, player_id = row

    assert row_awaits_its_walk(None, host, game_id=1, perspective=1, player_id=player_id) is False


@pytest.mark.parametrize(
    ("backfill_enabled", "admission"),
    [(False, CachedCompleteRowAdmission), (True, ScheduleRowAdmission)],
)
def test_a_stored_row_is_cached_unless_it_awaits_its_walk(row, backfill_enabled, admission):
    host, ctx, player_id = row
    if backfill_enabled:
        enable_backfill_earlier_turns(ctx)
    put_ensure_final_prior(ctx, player_id, generation=MARK_GENERATION - 1)
    rows = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    rows.put_row_without_notify(
        ctx.game_id, ctx.perspective, HOST_TURN, player_id, stored_complete_row()
    )

    resolved = resolve_row_stream_admission(
        host,
        player_id,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=HOST_TURN,
        load_scoreboard_turn=ctx.load_turn,
        persistence=rows,
        query_context=ctx,
    )

    assert isinstance(resolved, admission)
