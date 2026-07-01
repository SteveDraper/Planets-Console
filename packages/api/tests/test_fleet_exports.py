"""Golden tests for fleet analytic exports: registry, queries, and materialized tree."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.compute_services import resolve_fleet_services, turn_chain_through
from api.analytics.fleet.exports import EXPORT_CATALOG
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.exports import EXPORT_CATALOG as SCORES_EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.fleet_exports_helpers import (
    export_chain_query_context,
    materialize_fleet_tree,
    turn_with_score_delta,
)
from tests.fleet_fixtures import single_ship_turn
from tests.scores_exports_helpers import (
    GAME_ID,
    ensure_missing_step,
    first_player_id,
    perspective,
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
    ctx = export_chain_query_context(sample_turn)
    result = ctx.query("fleet", ["$.players"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_invalid_scope_without_player_id_for_composition_path(sample_turn):
    ctx = export_chain_query_context(sample_turn)
    result = ctx.query("fleet", ["$.composition.launcherTypes"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_materialized_tree_turn_one_empty_composition(sample_turn):
    player_id = first_player_id(sample_turn)
    turn_one = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
        ships=[],
    )
    ctx = export_chain_query_context(turn_one, stored_turns={1: turn_one})
    tree, _scope = materialize_fleet_tree(ctx, player_id, turn=1)
    assert tree["composition"] == {
        "hullTypes": {},
        "engineTypes": {},
        "beamTypes": {},
        "launcherTypes": {},
        "torpedoTypesLoaded": {},
        "maxTechLevel": {},
    }


def test_materialized_tree_composition_omits_unknown_placeholder_launchers(sample_turn):
    player_id = first_player_id(sample_turn)
    sighting = single_ship_turn(turn_number=5, ship_id=99, owner_id=player_id, x=100, y=100)
    turn = turn_with_score_delta(sighting, turn_number=5, owner_id=player_id, shipchange=1)
    turn = replace(turn, ships=sighting.ships)
    stored_turns = turn_chain_through(turn)
    stored_turns[5] = turn

    ctx = export_chain_query_context(
        turn,
        stored_turns=stored_turns,
        scheduler=InferenceRowScheduler(worker_count=0),
    )
    tree, _scope = materialize_fleet_tree(ctx, player_id, turn=5)
    ledger = tree["players"][0]
    assert len(ledger["records"]) == 2
    known_launcher_records = [
        record
        for record in ledger["records"]
        if record["fields"]["launchers"].get("kind") == "known"
    ]
    unknown_launcher_records = [
        record
        for record in ledger["records"]
        if record["fields"]["launchers"].get("kind") == "unknown"
    ]
    assert len(known_launcher_records) == 1
    assert len(unknown_launcher_records) == 1
    assert tree["composition"]["hullTypes"] == {"13": 1}
    assert tree["composition"]["beamTypes"] == {"3": 1}
    assert tree["composition"]["launcherTypes"] == {"6": 1}
    assert tree["composition"]["torpedoTypesLoaded"] == {}
    assert tree["composition"]["maxTechLevel"] == {"beams": 2}


def test_query_composition_launcher_types_path():
    player_id = 8
    turn = single_ship_turn(
        turn_number=1,
        ship_id=42,
        owner_id=player_id,
        x=1000,
        y=2000,
        hull_id=15,
        engine_id=3,
        beam_id=3,
        torpedoid=3,
    )
    ctx = export_chain_query_context(turn, stored_turns={1: turn})
    result = ctx.query(
        "fleet",
        [
            "$.composition.launcherTypes",
            "$.composition.hullTypes",
            "$.composition.maxTechLevel",
        ],
        {"turn": 1, "player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.composition.launcherTypes"].value == {"3": 1}
    assert result.paths["$.composition.hullTypes"].value == {"15": 1}
    assert result.paths["$.composition.maxTechLevel"].value == {
        "hulls": 1,
        "engines": 3,
        "launchers": 3,
        "beams": 2,
    }


def test_materialized_tree_includes_meta_host_turn(sample_turn):
    player_id = first_player_id(sample_turn)
    ctx = export_chain_query_context(sample_turn)
    tree, scope = materialize_fleet_tree(ctx, player_id)
    assert scope.turn == sample_turn.settings.turn
    assert tree["meta"]["hostTurn"] == sample_turn.settings.turn
    assert isinstance(tree["players"], list)
    assert tree["players"][0]["playerId"] == player_id


def test_materialized_tree_surfaces_not_started_scores_status(sample_turn):
    reset_inference_row_scheduler_for_tests()
    player_id = first_player_id(sample_turn)
    ctx = export_chain_query_context(sample_turn, scheduler=InferenceRowScheduler(worker_count=0))
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
    ctx = export_chain_query_context(sample_turn, persistence=persistence)
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
    ctx = export_chain_query_context(sample_turn, scheduler=scheduler)
    tree, _scope = materialize_fleet_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "in_progress"


def test_materialized_tree_includes_placeholder_records_with_incomplete_search(sample_turn):
    reset_inference_row_scheduler_for_tests()

    player_id = first_player_id(sample_turn)
    turn = turn_with_score_delta(
        sample_turn,
        turn_number=5,
        owner_id=player_id,
        shipchange=2,
    )
    stored_turns = turn_chain_through(turn)
    stored_turns[5] = turn

    ctx = export_chain_query_context(
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
    ctx = export_chain_query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "fleet",
        ["$.meta.searchStatus", "$.meta.solutionsHeld"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.meta.solutionsHeld"].value == 1


def test_ensure_fleet_export_materializes_snapshot_when_missing(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn_number = 8
    host_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
    )
    stored_turns = turn_chain_through(host_turn)
    ctx = export_chain_query_context(
        host_turn,
        persistence=persistence,
        stored_turns=stored_turns,
        seed_fleet_prerequisites_for=player_id,
    )
    fleet_services = resolve_fleet_services(ctx)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=turn_number,
        player_id=player_id,
    )
    put_persisted_row(
        persistence,
        host_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )

    assert not fleet_services.persistence.has_snapshot(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
    )

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert fleet_services.persistence.has_final_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
    )


def test_probe_and_walk_report_fleet_depends_on_scores_same_turn(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn_number = sample_turn.settings.turn
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        seed_fleet_prerequisites_for=player_id,
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=turn_number,
        player_id=player_id,
    )

    probe = ctx.probe("fleet", {"player_id": player_id})
    assert probe.status == "ok"
    assert probe.total_missing == 2
    scores_step = ensure_missing_step(
        probe,
        analytic_id="scores",
        turn=turn_number,
        player_id=player_id,
    )
    fleet_step = ensure_missing_step(
        probe,
        analytic_id="fleet",
        turn=turn_number,
        player_id=player_id,
    )
    assert scores_step.status == "not_persisted"
    assert fleet_step.status == "not_persisted"
    assert probe.missing_steps.index(scores_step) < probe.missing_steps.index(fleet_step)

    walk = walk_dependency_tree(ctx, "fleet", scope, visiting=set())
    assert walk.turn_unavailable is None
    walk_keys = [(step.analytic_id, step.turn) for step in walk.missing_steps]
    assert walk_keys == [("scores", turn_number), ("fleet", turn_number)]


def test_ensure_fleet_export_no_op_when_turn_not_stored(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    stored_turns = turn_chain_through(sample_turn)
    missing_turn = 999
    assert missing_turn not in stored_turns

    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    fleet_services = resolve_fleet_services(ctx)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=missing_turn,
        player_id=player_id,
    )

    assert EXPORT_CATALOG.ensure_export(ctx, scope) is True
    assert not fleet_services.persistence.has_snapshot(
        GAME_ID,
        perspective(sample_turn),
        missing_turn,
    )
