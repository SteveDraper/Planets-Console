"""Shared fixtures and helpers for scores export tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_services import (
    build_ephemeral_fleet_compute_services,
    turn_chain_through,
)
from api.analytics.fleet.held_solutions import FleetInferenceSupport
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
from api.analytics.scores.export_services import ScoresExportContext
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
    seed_fleet_prerequisites_for: int | None = None,
):
    turns = stored_turns if stored_turns is not None else turn_chain_through(sample_turn)

    def load_turn(turn_number: int):
        return turns.get(turn_number)

    scores_services = ScoresExportContext(persistence=persistence)
    if scheduler is not None:
        scores_services = ScoresExportContext(
            persistence=persistence,
            scheduler=scheduler,
        )

    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        stored_turns=turns,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={
            "scores": scores_services,
            "fleet": fleet_services,
        },
    )
    if seed_fleet_prerequisites_for is not None:
        seed_scores_fleet_unwind_through(
            ctx,
            through_turn=sample_turn.settings.turn,
            player_id=seed_fleet_prerequisites_for,
        )
    return ctx


def first_turn_from(sample_turn):
    return replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
        game=replace(sample_turn.game, turn=1),
    )


def prior_turn_chain(sample_turn, *, prior_turn: int = 110):
    prior_prior_turn = prior_turn - 1
    prior_turn_obj = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=prior_turn),
        game=replace(sample_turn.game, turn=prior_turn),
    )
    prior_prior_turn_obj = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=prior_prior_turn),
        game=replace(sample_turn.game, turn=prior_prior_turn),
    )
    stored_turns = turn_chain_through(sample_turn)
    stored_turns[prior_prior_turn] = prior_prior_turn_obj
    stored_turns[prior_turn] = prior_turn_obj
    stored_turns[sample_turn.settings.turn] = sample_turn
    return stored_turns, prior_turn_obj, prior_prior_turn_obj


def prior_turn_ensure_context(
    sample_turn,
    persistence: InferenceRowPersistenceService,
    *,
    prior_turn: int = 110,
    game_id: int = GAME_ID,
):
    stored_turns, _, _ = prior_turn_chain(sample_turn, prior_turn=prior_turn)
    player_id = first_player_id(sample_turn)

    def load_turn(turn_number: int):
        return stored_turns.get(turn_number)

    ctx = query_context(
        sample_turn,
        persistence=persistence,
        stored_turns=stored_turns,
    )
    seed_scores_fleet_unwind_through(ctx, through_turn=prior_turn, player_id=player_id)
    scope = ExportScope(
        game_id=game_id,
        perspective=perspective(sample_turn),
        turn=prior_turn,
        player_id=player_id,
    )
    return ctx, scope, player_id, stored_turns, load_turn


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
    time_limited: bool = False,
    ladder_complete: bool = False,
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
        time_limited=time_limited,
        ladder_complete=ladder_complete,
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


def seed_scores_fleet_unwind_through(
    ctx,
    *,
    through_turn: int,
    player_id: int,
) -> None:
    """Persist terminal scores rows and fleet snapshots for turns 1..through_turn-1."""
    from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
    from api.analytics.fleet.compute_services import FleetComputeServices
    from api.analytics.military_score_inference.solver import STATUS_EXACT

    fleet_services = ctx.export_services["fleet"]
    if not isinstance(fleet_services, FleetComputeServices):
        raise TypeError("seed_scores_fleet_unwind_through requires FleetComputeServices on ctx")

    scores_services = ctx.export_services["scores"]
    if scores_services.persistence is None:
        raise RuntimeError("seed_scores_fleet_unwind_through requires scores persistence")

    for turn_number in range(1, through_turn):
        turn = ctx.load_turn(turn_number)
        if turn is None:
            raise RuntimeError(
                f"seed_scores_fleet_unwind_through missing stored turn {turn_number}"
            )
        put_persisted_row(
            scores_services.persistence,
            turn,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seed",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
            host_turn=turn_number,
        )
        get_or_materialize_fleet_snapshot(
            fleet_services.persistence,
            ctx.game_id,
            ctx.perspective,
            turn,
            load_turn=ctx.load_turn,
            inference_materialization=fleet_services.inference_materialization,
        )


def scores_missing_step(probe, *, turn: int, player_id: int):
    """Assert probe reports exactly one missing scores step for turn/player."""
    assert probe.total_missing == 1
    return ensure_missing_step(probe, analytic_id="scores", turn=turn, player_id=player_id)


def ensure_missing_step(
    probe,
    *,
    analytic_id: str,
    turn: int,
    player_id: int | None,
):
    """Return the single missing ensure step for analytic/turn/player."""
    matches = [
        step
        for step in probe.missing_steps
        if step.analytic_id == analytic_id and step.turn == turn and step.player_id == player_id
    ]
    assert len(matches) == 1
    return matches[0]


def materialize_scores_tree(ctx, player_id: int, *, turn: int | None = None):
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn if turn is not None else ctx.ambient_turn,
        player_id=player_id,
    )
    return EXPORT_CATALOG.materialize_export_tree(ctx, scope), scope
