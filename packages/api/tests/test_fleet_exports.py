"""Golden tests for fleet analytic exports: registry, queries, and materialized tree."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from api.analytics.fleet.exports import EXPORT_CATALOG
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.exports import EXPORT_CATALOG as SCORES_EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.fleet_exports_helpers import (
    fleet_query_context,
    materialize_fleet_tree,
    turn_with_score_delta,
)
from tests.scores_exports_helpers import (
    first_player_id,
    put_persisted_row,
    schedule_row_with_ladder,
    ship_build_wire,
)


def test_export_registry_includes_non_empty_fleet_catalog():
    catalog = EXPORT_CATALOG
    assert catalog.analytic_id == "fleet"
    assert not catalog.is_empty
    assert catalog.ensure_dependencies == (
        EnsureDependency(analytic_id="scores", turn_delta=0, player_id="same"),
    )
    assert catalog.materialize_export_tree is not None
    assert catalog.ensure_export is not None


def test_scores_catalog_references_fleet_with_non_empty_target():
    catalog = SCORES_EXPORT_CATALOG
    assert catalog.ensure_dependencies == (
        EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
    )
    assert not EXPORT_CATALOG.is_empty


def test_invalid_scope_without_player_id_for_players_path(sample_turn):
    ctx = fleet_query_context(sample_turn)
    result = ctx.query("fleet", ["$.players"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_materialized_tree_includes_meta_host_turn(sample_turn):
    player_id = first_player_id(sample_turn)
    ctx = fleet_query_context(sample_turn)
    tree, scope = materialize_fleet_tree(ctx, player_id)
    assert scope.turn == sample_turn.settings.turn
    assert tree["meta"]["hostTurn"] == sample_turn.settings.turn
    assert isinstance(tree["players"], list)
    assert tree["players"][0]["playerId"] == player_id


def test_materialized_tree_surfaces_not_started_scores_status(sample_turn):
    reset_inference_row_scheduler_for_tests()
    player_id = first_player_id(sample_turn)
    ctx = fleet_query_context(sample_turn, scheduler=InferenceRowScheduler(worker_count=0))
    tree, _scope = materialize_fleet_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "not_started"
    assert "solutionsHeld" not in tree["meta"]


def test_materialized_tree_surfaces_complete_scores_status(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="no builds",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = fleet_query_context(sample_turn, persistence=persistence)
    tree, _scope = materialize_fleet_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "complete"
    assert "solutionsHeld" not in tree["meta"]


def test_materialized_tree_surfaces_in_progress_scores_status(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[],
    )
    ctx = fleet_query_context(sample_turn, scheduler=scheduler)
    tree, _scope = materialize_fleet_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "in_progress"


def test_materialized_tree_includes_placeholder_records_with_incomplete_search(sample_turn):
    reset_inference_row_scheduler_for_tests()
    from api.analytics.fleet.compute_services import turn_chain_through

    player_id = first_player_id(sample_turn)
    turn = turn_with_score_delta(
        sample_turn,
        turn_number=5,
        owner_id=player_id,
        shipchange=2,
    )
    stored_turns = turn_chain_through(turn)
    stored_turns[5] = turn

    ctx = fleet_query_context(
        turn,
        stored_turns=stored_turns,
        scheduler=InferenceRowScheduler(worker_count=0),
    )
    tree, _scope = materialize_fleet_tree(ctx, player_id, turn=5)
    ledger = tree["players"][0]
    assert len(ledger["records"]) == 2
    assert all(record["fields"]["hull"]["kind"] == "unknown" for record in ledger["records"])
    assert tree["meta"]["searchStatus"] == "not_started"


def test_query_meta_search_status_path(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="done",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 10,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="ship-a",
                            label="Freighter A",
                            hull_id=10,
                            engine_id=1,
                        ),
                    ],
                }
            ],
        ),
    )
    ctx = fleet_query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "fleet",
        ["$.meta.searchStatus", "$.meta.solutionsHeld"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.meta.solutionsHeld"].value == 1
