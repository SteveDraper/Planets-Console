"""Process-plane scores tier_solve leaf: pickle-safe wire, storage-rebuild SAT."""

from __future__ import annotations

import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.actions import (
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import (
    stream_tier_time_limit_seconds,
)
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import (
    apply_scores_tier_solve_step_result,
    build_scores_tier_solve_job_wire,
)
from api.analytics.scores.compute_plane.tier_solve_leaf import (
    WIRE_LADDER_STATE,
    WIRE_OBSERVATION,
    WIRE_STORAGE_ROOT,
    process_safe_ladder_state,
    run_scores_tier_solve_leaf,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.tier_row_run_registry import (
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores.tier_solve_backend import (
    SCORES_TIER_SOLVE_BACKEND_ENV,
    resolve_scores_tier_solve_backend,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeScope, DependencyOutputs
from api.compute.wire import orchestration_plane_skip_result
from api.serialization.turn import turn_info_to_json
from api.storage import open_file_backend

from tests.scores_exports_helpers import inference_target_player_id, minimal_stream_query_context


@pytest.fixture(autouse=True)
def _reset_scores_tier_registry():
    reset_tier_row_run_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()


def _tiny_policy_step(
    step_id: str = "tiny",
    *,
    max_seconds: float | None = None,
) -> InferenceTierPolicyStep:
    return InferenceTierPolicyStep(
        id=step_id,
        filters=InferenceCatalogFilters(
            hulls=ComponentFilter(tech_levels=(1,)),
            engines=ComponentFilter(tech_levels=(1,)),
            beams=ComponentFilter(tech_levels=(1,)),
            launchers=ComponentFilter(tech_levels=(1,)),
        ),
        beam_slot_counts="none",
        launcher_slot_counts="none",
        aggregate_allowlist={},
        alpha=0,
        max_seeds=0,
        max_seconds=max_seconds,
    )


def _put_turn_tree(tmp_path: Path, sample_turn) -> Path:
    storage = open_file_backend(tmp_path)
    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    turn_number = sample_turn.settings.turn
    storage.put(
        f"games/{game_id}/{perspective}/turns/{turn_number}",
        turn_info_to_json(sample_turn),
    )
    return tmp_path


def _scores_scope(sample_turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )


def _register_run(
    sample_turn,
    *,
    player_id: int,
    ladder: PolicyLadderState | None = None,
) -> RowRun:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )

    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
        query_context=minimal_stream_query_context(sample_turn),
    )
    run = RowRun(session)
    if ladder is not None:
        run.ladder_state = ladder
    register_row_run(run)
    return run


def _open_evidence_ctx(sample_turn):
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(scheduler=scheduler),
        },
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )


def _leaf_wire(
    *,
    tmp_path: Path,
    sample_turn,
    player_id: int,
    observation,
    ladder: PolicyLadderState,
) -> dict:
    return {
        WIRE_STORAGE_ROOT: str(tmp_path.resolve()),
        "gameId": sample_turn.game.id,
        "perspective": sample_turn.player.id,
        "turn": sample_turn.settings.turn,
        "playerId": player_id,
        WIRE_LADDER_STATE: process_safe_ladder_state(ladder),
        WIRE_OBSERVATION: observation,
        "timeLimitSeconds": stream_tier_time_limit_seconds(),
    }


def test_tier_solve_leaf_import_does_not_load_server_app_or_appkit():
    api_root = Path(__file__).resolve().parent.parent
    script = """
import sys
from api.analytics.scores.compute_plane.tier_solve_leaf import run_scores_tier_solve_leaf
blocked = [
    name
    for name in sys.modules
    if name == "server.app"
    or name.startswith("server.app.")
    or name == "AppKit"
    or name.startswith("AppKit.")
]
if blocked:
    raise SystemExit(f"unexpected modules: {blocked}")
if run_scores_tier_solve_leaf is None:
    raise SystemExit("leaf import failed")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_resolve_scores_tier_solve_backend_defaults_to_thread(monkeypatch):
    monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    monkeypatch.setattr("api.analytics.scores.tier_solve_backend.process_is_frozen", lambda: False)
    assert resolve_scores_tier_solve_backend() == "thread"


def test_resolve_scores_tier_solve_backend_env_process(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.analytics.scores.tier_solve_backend.process_is_frozen", lambda: False)
    assert resolve_scores_tier_solve_backend() == "process"


def test_resolve_scores_tier_solve_backend_frozen_stays_thread(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.analytics.scores.tier_solve_backend.process_is_frozen", lambda: True)
    assert resolve_scores_tier_solve_backend() == "thread"


def test_resolve_scores_step_backend_remaps_only_tier_solve(monkeypatch):
    from api.analytics.scores.compute_orchestration import (
        SCORES_MATERIALIZE,
        SCORES_TIER_SOLVE,
        resolve_scores_step_backend,
    )

    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.analytics.scores.tier_solve_backend.process_is_frozen", lambda: False)
    assert resolve_scores_step_backend(SCORES_TIER_SOLVE, "thread") == "process"
    assert resolve_scores_step_backend(SCORES_MATERIALIZE, "inline") == "inline"


def test_open_evidence_wire_is_process_safe_without_live_run_id(
    sample_turn,
    tmp_path,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert wire["runId"] is not None
    assert isinstance(wire[WIRE_STORAGE_ROOT], str)
    assert isinstance(wire[WIRE_LADDER_STATE], PolicyLadderState)
    assert wire[WIRE_LADDER_STATE].catalog is None
    assert wire[WIRE_LADDER_STATE].problem is None
    assert wire[WIRE_OBSERVATION] is not None
    pickle.dumps(wire)
    leaf_wire = dict(wire)
    leaf_wire.pop("runId")
    leaf_wire[WIRE_STORAGE_ROOT] = str(_put_turn_tree(tmp_path, sample_turn).resolve())
    result = run_scores_tier_solve_leaf(leaf_wire)
    assert result.outcome in {"continue", "persist", "waiting_deps", "complete"}


def test_orchestration_skip_stays_off_the_process_pool():
    skip = {
        "runId": None,
        "evidenceClosed": True,
        "orchestrationSkip": True,
    }
    result = orchestration_plane_skip_result(skip)
    assert result is not None
    assert result.outcome == "complete"
    assert orchestration_plane_skip_result({"runId": "live"}) is None


def test_leaf_skip_matches_in_process_empty_ladder(sample_turn, tmp_path) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = build_inference_observation(score, sample_turn)
    ladder = PolicyLadderState(policy_steps=())
    storage_root = _put_turn_tree(tmp_path, sample_turn)
    wire = _leaf_wire(
        tmp_path=storage_root,
        sample_turn=sample_turn,
        player_id=player_id,
        observation=observation,
        ladder=ladder,
    )
    in_process = PolicyLadderState(policy_steps=())
    run_policy_ladder_tier_step(
        in_process,
        observation,
        sample_turn,
        time_limit_seconds=stream_tier_time_limit_seconds(),
    )
    result = run_scores_tier_solve_leaf(wire)
    snapshot = result.payload[WIRE_LADDER_STATE] if isinstance(result.payload, dict) else None
    assert in_process.ladder_complete is True
    if isinstance(snapshot, PolicyLadderState):
        assert snapshot.last_status == in_process.last_status
        assert snapshot.ladder_complete is True


def test_leaf_freighter_only_matches_solve_inference_problem(sample_turn, tmp_path) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = replace(
        build_inference_observation(score, sample_turn),
        military_delta_2x=0,
        warship_delta=0,
        freighter_delta=1,
        priority_point_delta=0,
    )
    step = _tiny_policy_step()
    ladder = PolicyLadderState(policy_steps=(step,))
    catalog = build_action_catalog_from_turn(observation, sample_turn, policy_step=step)
    problem = build_inference_problem(observation, catalog, max_solutions=1)
    expected = solve_inference_problem(problem)
    assert expected.status == STATUS_EXACT
    assert expected.diagnostics.get("solver_status") == "FREIGHTER_ONLY_FAST_PATH"

    result = run_scores_tier_solve_leaf(
        _leaf_wire(
            tmp_path=_put_turn_tree(tmp_path, sample_turn),
            sample_turn=sample_turn,
            player_id=player_id,
            observation=observation,
            ladder=ladder,
        )
    )
    snapshot = result.payload[WIRE_LADDER_STATE]
    assert snapshot.last_status == expected.status
    assert snapshot.last_diagnostics.get("solver_status") == "FREIGHTER_ONLY_FAST_PATH"


def test_leaf_small_sat_matches_solve_inference_problem(sample_turn, tmp_path) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = replace(
        build_inference_observation(score, sample_turn),
        military_delta_2x=1,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
    )
    step = _tiny_policy_step()
    ladder = PolicyLadderState(policy_steps=(step,))
    catalog = build_action_catalog_from_turn(observation, sample_turn, policy_step=step)
    problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=1,
        time_limit_seconds=1.0,
    )
    expected = solve_inference_problem(problem)
    result = run_scores_tier_solve_leaf(
        _leaf_wire(
            tmp_path=_put_turn_tree(tmp_path, sample_turn),
            sample_turn=sample_turn,
            player_id=player_id,
            observation=observation,
            ladder=ladder,
        )
    )
    snapshot = result.payload[WIRE_LADDER_STATE]
    assert snapshot.last_status == expected.status


def test_continue_payload_advances_parent_ladder_without_child_rowrun(
    sample_turn,
    tmp_path,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = build_inference_observation(score, sample_turn)
    steps = (_tiny_policy_step("a", max_seconds=0.0), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    assert parent.ladder_state is not None
    assert parent.ladder_state.next_step_index == 0

    result = run_scores_tier_solve_leaf(
        _leaf_wire(
            tmp_path=_put_turn_tree(tmp_path, sample_turn),
            sample_turn=sample_turn,
            player_id=player_id,
            observation=observation,
            ladder=PolicyLadderState(policy_steps=steps),
        )
    )
    apply_scores_tier_solve_step_result(parent, result)
    assert parent.ladder_state is not None
    if result.outcome == "continue":
        assert parent.ladder_state.next_step_index == 1
        assert parent.ladder_state.catalog is None
    else:
        assert parent.ladder_state.ladder_complete is True
