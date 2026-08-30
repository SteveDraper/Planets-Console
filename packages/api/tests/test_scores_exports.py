"""Golden tests for scores analytic exports: registry, queries, and wire helpers."""

from __future__ import annotations

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import EnsureDependency
from api.analytics.military_score_inference.inference_api_payload import (
    INFERENCE_ADMISSION_SKIP_STATUSES,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_wire import (
    ranked_solutions_from_wire,
    solutions_diagnostics_from_wire_complete_event,
)
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    first_turn_from,
    inference_target_player_id,
    materialize_scores_tree,
    put_persisted_row,
    schedule_row_with_ladder,
    scores_query_context,
    ship_build_wire,
    stream_scope_for_turn,
)


def test_export_registry_includes_non_empty_scores_catalog():
    catalog = EXPORT_CATALOG
    assert catalog.analytic_id == "scores"
    assert not catalog.is_empty
    assert catalog.ensure_dependencies == (
        EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
    )
    assert catalog.materialize_export_tree is not None
    assert catalog.ensure_export is not None


def test_complete_empty_solutions_returns_path_none(sample_turn, persistence):
    player_id = inference_target_player_id(sample_turn)
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
    ctx = scores_query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "scores",
        ["$.solutions[0]", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].kind == "value"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0]"].kind == "none"


def test_invalid_scope_without_player_id(sample_turn):
    ctx = scores_query_context(sample_turn)
    result = ctx.query("scores", ["$.solutions"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_ranked_solutions_from_wire_orders_by_objective_value():
    solutions = ranked_solutions_from_wire(
        [
            {
                "objectiveValue": 10,
                "actions": [],
                "shipBuilds": [{"hullId": 1}],
            },
            {
                "objectiveValue": 99,
                "actions": [],
                "shipBuilds": [{"hullId": 2}],
            },
        ]
    )
    assert solutions[0]["objectiveValue"] == 99
    assert solutions[1]["objectiveValue"] == 10


def test_solutions_diagnostics_from_wire_complete_event():
    solutions, diagnostics, solutions_held = solutions_diagnostics_from_wire_complete_event(
        {
            "type": "complete",
            "status": STATUS_EXACT,
            "summary": "wire",
            "solutionCount": 1,
            "isComplete": True,
            "solutions": [
                {
                    "objectiveValue": 55,
                    "actions": [],
                    "shipBuilds": [{"hullId": 7}],
                }
            ],
            "diagnostics": {"note": "cached"},
        }
    )
    assert solutions_held == 1
    assert solutions[0]["objectiveValue"] == 55
    assert diagnostics == {"note": "cached"}


def test_top_solution_query_returns_full_build(sample_turn, persistence):
    player_id = inference_target_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="multi-ship",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 80,
                    "actions": [
                        {
                            "actionId": "planet_defense_posts_added_total",
                            "label": "Defense",
                            "count": 2,
                        }
                    ],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="ship-a",
                            label="Freighter A",
                            hull_id=10,
                            engine_id=1,
                        ),
                        ship_build_wire(
                            combo_id="ship-b",
                            label="Freighter B",
                            hull_id=11,
                            engine_id=2,
                        ),
                    ],
                }
            ],
        ),
    )
    ctx = scores_query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "scores",
        ["$.solutions[0].shipBuilds", "$.solutions[0].actions"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    ship_builds = result.paths["$.solutions[0].shipBuilds"].value
    actions = result.paths["$.solutions[0].actions"].value
    assert len(ship_builds) == 2
    assert ship_builds[0]["hullId"] == 10
    assert ship_builds[1]["hullId"] == 11
    assert actions[0]["count"] == 2


def test_resolve_scores_services_fails_without_injection(sample_turn):
    player_id = inference_target_player_id(sample_turn)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=lambda turn_number: (
            sample_turn if turn_number == sample_turn.settings.turn else None
        ),
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    with pytest.raises(RuntimeError, match="requires 'scores' in ctx.export_services"):
        materialize_scores_tree(ctx, player_id)


def test_resolve_scores_services_fails_on_wrong_type(sample_turn):
    player_id = inference_target_player_id(sample_turn)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=lambda turn_number: (
            sample_turn if turn_number == sample_turn.settings.turn else None
        ),
        export_services={"scores": object()},
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    with pytest.raises(RuntimeError, match="must be ScoresExportContext"):
        materialize_scores_tree(ctx, player_id)


def test_first_turn_materializes_complete_without_ensure(sample_turn):
    first_turn = first_turn_from(sample_turn)
    player_id = inference_target_player_id(first_turn)

    ctx = scores_query_context(
        first_turn,
        stored_turns={1: first_turn},
    )
    result = ctx.query(
        "scores",
        ["$.meta.searchStatus", "$.solutions[0]"],
        {"player_id": player_id},
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0]"].kind == "none"


def test_scheduler_branch_surfaces_ladder_diagnostics_via_query(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = inference_target_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None
    assert run.ladder_state is not None
    run.ladder_state.last_diagnostics = {"source": "scheduler_ladder"}

    ctx = scores_query_context(sample_turn, scheduler=scheduler)
    result = ctx.query(
        "scores",
        ["$.diagnostics.solver.source", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "in_progress"
    assert result.paths["$.diagnostics.solver.source"].value == "scheduler_ladder"

    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["diagnostics"]["solver"]["source"] == "scheduler_ladder"


_PRODUCT_STATUS_QUERY_PATHS = [
    "$.meta.searchStatus",
    "$.status",
    "$.solutions[0]",
    "$.placeholders",
    "$.unexplainedMilitaryDelta2x",
    "$.solution.ships",
    "$.solution.diagnostics",
]


def _query_product_status(ctx, player_id: int):
    return ctx.query(
        "scores",
        _PRODUCT_STATUS_QUERY_PATHS,
        {"player_id": player_id},
        force_inline_ensure=True,
    )


@pytest.mark.parametrize(
    ("status", "leftover_2x"),
    [
        (STATUS_MODERATE_RESIDUAL, 22),
        (STATUS_MINE_SCORE_RESIDUAL, 54),
        (STATUS_NO_EXACT_SOLUTION, 8),
    ],
)
def test_residual_export_exposes_product_status_leftover_and_empty_placeholders(
    status: str,
    leftover_2x: int,
    sample_turn,
    persistence,
):
    player_id = inference_target_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=status,
            summary=status,
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=[],
            unexplained_military_delta_2x=leftover_2x,
        ),
    )
    result = _query_product_status(
        scores_query_context(sample_turn, persistence=persistence),
        player_id,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.status"].value == status
    assert result.paths["$.solutions[0]"].kind == "none"
    assert result.paths["$.placeholders"].value == []
    assert result.paths["$.unexplainedMilitaryDelta2x"].value == leftover_2x
    assert result.paths["$.solution.ships"].kind == "none"
    assert result.paths["$.solution.diagnostics"].kind == "none"


def test_residual_export_exposes_unknown_military_and_freighter_placeholders(
    sample_turn,
    persistence,
):
    from api.analytics.military_score_inference.post_unsat_placeholders import (
        UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
    )
    from api.analytics.military_score_inference.ship_build_combos import (
        GENERIC_FREIGHTER_COMBO_ID,
    )
    from api.concepts.hulls import (
        GENERIC_FREIGHTER_SENTINEL_HULL_ID,
        UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
    )

    player_id = inference_target_player_id(sample_turn)
    placeholders = [
        {
            "id": UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
            "hullId": UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
            "count": 2,
            "militaryScoreDelta2xMin": 232,
            "militaryScoreDelta2xMax": 2180,
            "buildSlotUsage": 1,
        },
        {
            "id": GENERIC_FREIGHTER_COMBO_ID,
            "hullId": GENERIC_FREIGHTER_SENTINEL_HULL_ID,
            "count": 1,
            "buildSlotUsage": 1,
        },
    ]
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_MODERATE_RESIDUAL,
            summary="Moderate military leftover (11)",
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=placeholders,
            unexplained_military_delta_2x=22,
        ),
    )
    result = _query_product_status(
        scores_query_context(sample_turn, persistence=persistence),
        player_id,
    )
    assert result.status == "ok"
    assert result.paths["$.placeholders"].value == placeholders
    assert result.paths["$.unexplainedMilitaryDelta2x"].value == 22
    assert result.paths["$.solutions[0]"].kind == "none"


@pytest.mark.parametrize("status", sorted(INFERENCE_ADMISSION_SKIP_STATUSES))
def test_skip_export_exposes_per_reason_status_without_leftover(
    status: str,
    sample_turn,
    persistence,
):
    player_id = inference_target_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=status,
            summary=status,
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=[],
        ),
    )
    result = _query_product_status(
        scores_query_context(sample_turn, persistence=persistence),
        player_id,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.status"].value == status
    assert result.paths["$.solutions[0]"].kind == "none"
    assert result.paths["$.placeholders"].value == []
    assert result.paths["$.unexplainedMilitaryDelta2x"].kind == "none"
    assert result.paths["$.solution.ships"].kind == "none"
    assert result.paths["$.solution.diagnostics"].kind == "none"


def test_exact_export_exposes_product_status_without_leftover_or_placeholders(
    sample_turn,
    persistence,
):
    player_id = inference_target_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="exact",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    result = _query_product_status(
        scores_query_context(sample_turn, persistence=persistence),
        player_id,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.status"].value == STATUS_EXACT
    assert result.paths["$.placeholders"].kind == "none"
    assert result.paths["$.unexplainedMilitaryDelta2x"].kind == "none"


def test_product_status_paths_require_player_id(sample_turn):
    ctx = scores_query_context(sample_turn)
    result = ctx.query("scores", ["$.status", "$.placeholders", "$.unexplainedMilitaryDelta2x"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"
