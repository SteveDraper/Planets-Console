"""Golden tests for scores analytic exports."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_context import ScoresExportContext, make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_STOPPED
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_materialization import ranked_solutions_from_wire
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


@pytest.fixture
def persistence(memory_backend):
    return InferenceRowPersistenceService(memory_backend)


def _perspective(sample_turn) -> int:
    return sample_turn.player.id


def _query_context(
    sample_turn,
    *,
    persistence: InferenceRowPersistenceService | None = None,
    scheduler: InferenceRowScheduler | None = None,
    stored_turns: dict[int, object] | None = None,
):
    turns = stored_turns or {sample_turn.settings.turn: sample_turn}

    def load_turn(turn_number: int):
        return turns.get(turn_number)

    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        scores_export=ScoresExportContext(
            persistence=persistence,
            scheduler=scheduler,
        ),
    )


def test_export_registry_includes_non_empty_scores_catalog():
    catalog = EXPORT_CATALOG
    assert catalog.analytic_id == "scores"
    assert not catalog.is_empty
    assert catalog.ensure_dependencies == ()
    assert catalog.materialize_export_tree is not None
    assert catalog.ensure_export is not None


def test_complete_empty_solutions_returns_path_none(sample_turn, persistence):
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        _perspective(sample_turn),
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="no builds",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = _query_context(sample_turn, persistence=persistence)
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


def test_not_started_when_no_persistence_or_scheduler(sample_turn):
    reset_inference_row_scheduler_for_tests()
    player_id = sample_turn.scores[0].ownerid
    ctx = _query_context(sample_turn, scheduler=InferenceRowScheduler(worker_count=0))
    tree = EXPORT_CATALOG.materialize_export_tree(ctx, ctx._resolve_scope({"player_id": player_id}))
    assert tree["meta"]["searchStatus"] == "not_started"
    assert tree["solutions"] == []


def test_in_progress_when_scheduler_holds_row(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=_perspective(sample_turn),
    )
    assert scheduled is not None
    run = scheduler.row_run_for_player(
        InferenceStreamScope(
            game_id=628580,
            perspective=_perspective(sample_turn),
            turn_number=111,
        ),
        player_id,
    )
    assert run is not None
    run.ladder_state = PolicyLadderState(
        policy_steps=(),
        merged_solutions=[
            InferenceSolution(
                objective_value=50,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=2,
                    ),
                ),
                ship_builds=(
                    InferenceSolutionShipBuild(
                        combo_id="combo-1",
                        label="Small Deep Space Freighter",
                        count=1,
                        hull_id=1,
                        engine_id=5,
                        beam_id=None,
                        torp_id=None,
                        beam_count=0,
                        launcher_count=0,
                    ),
                ),
            )
        ],
    )

    ctx = _query_context(sample_turn, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    tree = EXPORT_CATALOG.materialize_export_tree(ctx, scope)
    assert tree["meta"]["searchStatus"] == "in_progress"
    assert tree["meta"]["solutionsHeld"] == 1
    top = tree["solutions"][0]
    assert top["shipBuilds"][0]["hullId"] == 1
    assert top["actions"][0]["actionId"] == "planet_defense_posts_added_total"


def test_top_solution_query_returns_full_build(sample_turn, persistence):
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        _perspective(sample_turn),
        sample_turn.settings.turn,
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
                        {
                            "comboId": "ship-a",
                            "label": "Freighter A",
                            "count": 1,
                            "hullId": 10,
                            "engineId": 1,
                            "beamId": None,
                            "torpId": None,
                            "beamCount": 0,
                            "launcherCount": 0,
                        },
                        {
                            "comboId": "ship-b",
                            "label": "Freighter B",
                            "count": 1,
                            "hullId": 11,
                            "engineId": 2,
                            "beamId": None,
                            "torpId": None,
                            "beamCount": 0,
                            "launcherCount": 0,
                        },
                    ],
                }
            ],
        ),
    )
    ctx = _query_context(sample_turn, persistence=persistence)
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


def test_persisted_row_replay_overrides_scheduler_state(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        _perspective(sample_turn),
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 99,
                    "actions": [],
                    "shipBuilds": [
                        {
                            "comboId": "cached-combo",
                            "label": "Cached hull",
                            "count": 1,
                            "hullId": 42,
                            "engineId": 7,
                            "beamId": None,
                            "torpId": None,
                            "beamCount": 0,
                            "launcherCount": 0,
                        }
                    ],
                }
            ],
        ),
    )
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=_perspective(sample_turn),
    )
    run = scheduler.row_run_for_player(
        InferenceStreamScope(
            game_id=628580,
            perspective=_perspective(sample_turn),
            turn_number=111,
        ),
        player_id,
    )
    assert run is not None
    run.ladder_state = PolicyLadderState(
        policy_steps=(),
        merged_solutions=[
            InferenceSolution(
                objective_value=1,
                actions=(),
                ship_builds=(
                    InferenceSolutionShipBuild(
                        combo_id="live-combo",
                        label="Live hull",
                        count=1,
                        hull_id=1,
                        engine_id=1,
                        beam_id=None,
                        torp_id=None,
                        beam_count=0,
                        launcher_count=0,
                    ),
                ),
            )
        ],
    )

    ctx = _query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    result = ctx.query(
        "scores",
        ["$.solutions[0].shipBuilds[0].hullId", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0].shipBuilds[0].hullId"].value == 42


def test_invalid_scope_without_player_id(sample_turn):
    ctx = _query_context(sample_turn)
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


def test_first_turn_materializes_complete_without_ensure(sample_turn):
    first_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
    )
    player_id = first_turn.scores[0].ownerid

    def load_turn(turn_number: int):
        if turn_number == 1:
            return first_turn
        return None

    ctx = make_analytic_query_context(
        first_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
    )
    result = ctx.query(
        "scores",
        ["$.meta.searchStatus", "$.solutions[0]"],
        {"player_id": player_id},
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0]"].kind == "none"


def test_paused_when_globally_paused_on_active_stream(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(stream_scope)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=_perspective(sample_turn),
    )
    assert scheduled is not None
    run = scheduler.row_run_for_player(stream_scope, player_id)
    assert run is not None
    run.ladder_state = PolicyLadderState(
        policy_steps=(),
        merged_solutions=[
            InferenceSolution(
                objective_value=25,
                actions=(),
                ship_builds=(),
            )
        ],
    )
    scheduler.pause_globally(stream_scope)

    ctx = _query_context(sample_turn, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    tree = EXPORT_CATALOG.materialize_export_tree(ctx, scope)
    assert tree["meta"]["searchStatus"] == "paused"


def test_stopped_when_ladder_last_status_stopped(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=_perspective(sample_turn),
    )
    assert scheduled is not None
    run = scheduler.row_run_for_player(stream_scope, player_id)
    assert run is not None
    run.ladder_state = PolicyLadderState(
        policy_steps=(),
        merged_solutions=[
            InferenceSolution(
                objective_value=40,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=1,
                    ),
                ),
                ship_builds=(),
            )
        ],
        last_status=STATUS_STOPPED,
    )

    ctx = _query_context(sample_turn, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    tree = EXPORT_CATALOG.materialize_export_tree(ctx, scope)
    assert tree["meta"]["searchStatus"] == "stopped"
    assert tree["meta"]["solutionsHeld"] == 1
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False


def test_stopped_when_persisted_row_stopped(sample_turn, persistence):
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        _perspective(sample_turn),
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_STOPPED,
            summary="stopped",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 40,
                    "actions": [
                        {
                            "actionId": "planet_defense_posts_added_total",
                            "label": "Planet defense",
                            "count": 1,
                        }
                    ],
                    "shipBuilds": [],
                }
            ],
        ),
    )
    ctx = _query_context(sample_turn, persistence=persistence)
    scope = ctx._resolve_scope({"player_id": player_id})
    tree = EXPORT_CATALOG.materialize_export_tree(ctx, scope)
    assert tree["meta"]["searchStatus"] == "stopped"
    assert tree["meta"]["solutionsHeld"] == 1
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False


def test_ensure_prior_turn_sync_puts_persistable_row(sample_turn, persistence):
    player_id = sample_turn.scores[0].ownerid
    prior_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=110),
        game=replace(sample_turn.game, turn=110),
    )
    prior_prior_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=109),
        game=replace(sample_turn.game, turn=109),
    )
    stored_turns = {
        109: prior_prior_turn,
        110: prior_turn,
        sample_turn.settings.turn: sample_turn,
    }

    def load_turn(turn_number: int):
        return stored_turns.get(turn_number)

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        scores_export=ScoresExportContext(persistence=persistence),
    )
    scope = ExportScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn=110,
        player_id=player_id,
    )
    assert persistence.get_row(628580, _perspective(sample_turn), 110, player_id) is None

    EXPORT_CATALOG.ensure_export(ctx, scope)

    row = persistence.get_row(628580, _perspective(sample_turn), 110, player_id)
    assert row is not None
    assert row.status in {STATUS_EXACT, "no_exact_solution"}


def test_ensure_schedules_inference_row_on_current_turn(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )
    ctx = _query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    assert scheduler.row_run_for_player(stream_scope, player_id) is None

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is not None


def test_ensure_no_op_when_row_already_scheduled(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=_perspective(sample_turn),
    )
    run_before = scheduler.row_run_for_player(stream_scope, player_id)
    assert run_before is not None

    ctx = _query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    EXPORT_CATALOG.ensure_export(ctx, scope)

    run_after = scheduler.row_run_for_player(stream_scope, player_id)
    assert run_after is run_before


def test_ensure_no_op_when_row_persisted(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=_perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )
    persistence.put_row(
        628580,
        _perspective(sample_turn),
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = _query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is None


def test_first_turn_immediate_complete_is_persisted(sample_turn):
    first_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
    )
    player_id = first_turn.scores[0].ownerid

    def load_turn(turn_number: int):
        if turn_number == 1:
            return first_turn
        return None

    ctx = make_analytic_query_context(
        first_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
    )
    scope = ctx._resolve_scope({"player_id": player_id})

    tree = EXPORT_CATALOG.materialize_export_tree(ctx, scope)
    assert tree["meta"]["searchStatus"] == "complete"
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is True
