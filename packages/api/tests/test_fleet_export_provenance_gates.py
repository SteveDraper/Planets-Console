"""F7.3: fleet export ensure/probe provenance gates and compute short-circuit."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import ExportScope
from api.analytics.fleet.chain import (
    _materialize_fleet_ledger_chain_for_player,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.exports import EXPORT_CATALOG
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.export_chain_test_fixtures import GAME_ID, export_chain_query_context
from tests.fleet_exports_helpers import materialize_fleet_tree
from tests.scores_exports_helpers import (
    ensure_missing_step,
    first_player_id,
    perspective,
    put_persisted_row,
)


def _partial_persisted_ledger(player_id: int) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=False,
        ),
    )


def _turn_chain_through(sample_turn, *, through_turn: int):
    chain = {}
    for turn_number in range(1, through_turn + 1):
        chain[turn_number] = replace(
            sample_turn,
            settings=replace(sample_turn.settings, turn=turn_number),
            game=replace(sample_turn.game, turn=turn_number),
        )
    return chain


def test_partial_fleet_ledger_is_not_ensure_satisfied(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn_number = 8
    stored_turns = _turn_chain_through(sample_turn, through_turn=turn_number)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    fleet_services = ctx.export_services["fleet"]
    fleet_services.persistence.put_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
        _partial_persisted_ledger(player_id),
    )

    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=turn_number,
        player_id=player_id,
    )

    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False
    assert EXPORT_CATALOG.is_ensure_satisfied is not None
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is False


def test_probe_fleet_at_8_lists_missing_scores_5_6_7_with_partial_ledgers(
    sample_turn,
    persistence,
):
    """628580-style gap: partial fleet@8 with no scores rows for turns 5-7."""
    player_id = first_player_id(sample_turn)
    turn_number = 8
    stored_turns = _turn_chain_through(sample_turn, through_turn=turn_number)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    fleet_services = ctx.export_services["fleet"]
    fleet_services.persistence.put_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
        _partial_persisted_ledger(player_id),
    )
    put_persisted_row(
        persistence,
        stored_turns[3],
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )

    probe = ctx.probe("fleet", {"turn": turn_number, "player_id": player_id})
    assert probe.status == "ok"

    missing_scores_turns = sorted(
        step.turn
        for step in probe.missing_steps
        if step.analytic_id == "scores" and step.player_id == player_id
    )
    assert {5, 6, 7}.issubset(missing_scores_turns)

    walk = walk_dependency_tree(
        ctx,
        "fleet",
        ExportScope(
            game_id=GAME_ID,
            perspective=perspective(sample_turn),
            turn=turn_number,
            player_id=player_id,
        ),
        visiting=set(),
    )
    walk_scores_turns = sorted(
        step.turn
        for step in walk.missing_steps
        if step.analytic_id == "scores" and step.player_id == player_id
    )
    assert {5, 6, 7}.issubset(walk_scores_turns)
    fleet_step = ensure_missing_step(
        probe,
        analytic_id="fleet",
        turn=turn_number,
        player_id=player_id,
    )
    assert fleet_step.status == "not_persisted"


def test_get_or_materialize_fleet_snapshot_does_not_short_circuit_on_partial_cache(
    sample_turn,
    persistence,
):
    player_id = first_player_id(sample_turn)
    turn_number = 8
    stored_turns = _turn_chain_through(sample_turn, through_turn=turn_number)
    turn = stored_turns[turn_number]
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    fleet_services = ctx.export_services["fleet"]
    fleet_services.persistence.put_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
        _partial_persisted_ledger(player_id),
    )

    with patch(
        "api.analytics.fleet.chain._materialize_fleet_snapshot_chain",
        side_effect=AssertionError("must not gap-fill when only partial cache exists"),
    ):
        with pytest.raises(AssertionError, match="must not gap-fill"):
            get_or_materialize_fleet_snapshot(
                fleet_services.persistence,
                GAME_ID,
                perspective(sample_turn),
                turn,
                load_turn=ctx.load_turn,
                inference_materialization=fleet_services.inference_materialization,
            )


def test_get_or_materialize_fleet_ledger_rechains_when_cached_partial(
    sample_turn,
    persistence,
):
    player_id = first_player_id(sample_turn)
    turn_number = 8
    stored_turns = _turn_chain_through(sample_turn, through_turn=turn_number)
    turn = stored_turns[turn_number]
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    fleet_services = ctx.export_services["fleet"]
    fleet_services.persistence.put_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
        _partial_persisted_ledger(player_id),
    )

    materialize_calls = 0
    original = _materialize_fleet_ledger_chain_for_player

    def counting_materialize(*args, **kwargs):
        nonlocal materialize_calls
        materialize_calls += 1
        return original(*args, **kwargs)

    with patch(
        "api.analytics.fleet.chain._materialize_fleet_ledger_chain_for_player",
        side_effect=counting_materialize,
    ):
        get_or_materialize_fleet_snapshot(
            fleet_services.persistence,
            GAME_ID,
            perspective(sample_turn),
            turn,
            load_turn=ctx.load_turn,
            inference_materialization=fleet_services.inference_materialization,
        )

    assert materialize_calls >= 1
    loaded = fleet_services.persistence.get_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
    )
    assert loaded is not None
    assert loaded.provenance.is_final is False


def test_ensure_fleet_export_succeeds_when_provenance_final(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn_number = sample_turn.settings.turn
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        seed_fleet_prerequisites_for=player_id,
    )
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=turn_number,
        player_id=player_id,
    )

    assert EXPORT_CATALOG.ensure_export(ctx, scope) is True
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is True

    tree, _ = materialize_fleet_tree(ctx, player_id)
    assert tree["meta"]["hostTurn"] == turn_number
