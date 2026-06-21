"""Shared fixtures and helpers for scores export tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_context import ScoresExportContext, make_analytic_query_context
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
GAME_ID = 628580


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


def perspective(sample_turn) -> int:
    return sample_turn.player.id


def first_player_id(sample_turn) -> int:
    return sample_turn.scores[0].ownerid


def stream_scope_for_turn(
    sample_turn,
    *,
    game_id: int = GAME_ID,
    turn_number: int | None = None,
    perspective_id: int | None = None,
) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=game_id,
        perspective=perspective_id if perspective_id is not None else perspective(sample_turn),
        turn_number=turn_number if turn_number is not None else sample_turn.settings.turn,
    )


def query_context(
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
        export_services={
            "scores": ScoresExportContext(
                persistence=persistence,
                scheduler=scheduler,
            ),
        },
    )


def first_turn_from(sample_turn):
    return replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
    )


def ship_build_wire(
    *,
    combo_id: str,
    label: str,
    hull_id: int,
    engine_id: int = 1,
    count: int = 1,
) -> dict[str, object]:
    return {
        "comboId": combo_id,
        "label": label,
        "count": count,
        "hullId": hull_id,
        "engineId": engine_id,
        "beamId": None,
        "torpId": None,
        "beamCount": 0,
        "launcherCount": 0,
    }


def ship_build_domain(
    *,
    combo_id: str,
    label: str,
    hull_id: int,
    engine_id: int = 1,
    count: int = 1,
) -> InferenceSolutionShipBuild:
    return InferenceSolutionShipBuild(
        combo_id=combo_id,
        label=label,
        count=count,
        hull_id=hull_id,
        engine_id=engine_id,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
    )


def inference_solution(
    *,
    objective_value: int,
    actions: tuple[InferenceSolutionAction, ...] = (),
    ship_builds: tuple[InferenceSolutionShipBuild, ...] = (),
) -> InferenceSolution:
    return InferenceSolution(
        objective_value=objective_value,
        actions=actions,
        ship_builds=ship_builds,
    )


def schedule_row_with_ladder(
    scheduler: InferenceRowScheduler,
    sample_turn,
    player_id: int,
    *,
    merged_solutions: list[InferenceSolution],
    last_status: str | None = None,
    game_id: int = GAME_ID,
) -> InferenceStreamScope:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=game_id,
        perspective=perspective(sample_turn),
    )
    assert scheduled is not None
    stream_scope = stream_scope_for_turn(sample_turn, game_id=game_id)
    run = scheduler.row_run_for_player(stream_scope, player_id)
    assert run is not None
    run.ladder_state = PolicyLadderState(
        policy_steps=(),
        merged_solutions=merged_solutions,
        last_status=last_status,
    )
    return stream_scope


def put_persisted_row(
    persistence: InferenceRowPersistenceService,
    sample_turn,
    player_id: int,
    row: PersistedInferenceRow,
    *,
    game_id: int = GAME_ID,
    host_turn: int | None = None,
) -> None:
    persistence.put_row(
        game_id,
        perspective(sample_turn),
        host_turn if host_turn is not None else sample_turn.settings.turn,
        player_id,
        row,
    )


def materialize_scores_tree(ctx, player_id: int):
    scope = ctx._resolve_scope({"player_id": player_id})
    return EXPORT_CATALOG.materialize_export_tree(ctx, scope), scope
