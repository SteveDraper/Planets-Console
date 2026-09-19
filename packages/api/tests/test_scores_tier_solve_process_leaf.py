"""Process-plane scores tier_solve leaf: pickle-safe wire, storage-rebuild SAT."""

from __future__ import annotations

import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
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
    ScoresPersistencePolicy,
    apply_scores_tier_solve_step_result,
    build_scores_tier_solve_job_wire,
    map_scores_tier_solve_remote_result,
)
from api.analytics.scores.compute_plane.tier_solve_leaf import (
    process_safe_ladder_state,
    run_scores_tier_solve_leaf,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.tier_row_run_registry import (
    get_row_run_for_scope,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores.tier_solve_backend import (
    SCORES_TIER_SOLVE_BACKEND_ENV,
    resolve_scores_tier_solve_backend,
)
from api.analytics.scores.tier_solve_wire import (
    WIRE_EVIDENCE_CLOSED,
    WIRE_GAME_ID,
    WIRE_LADDER_STATE,
    WIRE_OBSERVATION,
    WIRE_ORCHESTRATION_SKIP,
    WIRE_PERSPECTIVE,
    WIRE_PLAYER_ID,
    WIRE_RUN_ID,
    WIRE_STORAGE_ROOT,
    WIRE_TIME_LIMIT_SECONDS,
    WIRE_TURN,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeScope, DependencyOutputs
from api.compute.wire import StepResult, coerce_step_result, orchestration_plane_skip_result
from api.errors import NotFoundError
from api.serialization.turn import turn_info_to_json
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage import open_file_backend

from tests.scores_exports_helpers import inference_target_player_id, minimal_stream_query_context

_PROCESS_REBUILD_KEYS = frozenset(
    {
        WIRE_STORAGE_ROOT,
        WIRE_LADDER_STATE,
        WIRE_OBSERVATION,
        WIRE_TIME_LIMIT_SECONDS,
    }
)
_THREAD_IDENTITY_KEYS = frozenset(
    {
        WIRE_RUN_ID,
        WIRE_GAME_ID,
        WIRE_PERSPECTIVE,
        WIRE_TURN,
        WIRE_PLAYER_ID,
    }
)


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
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _opt_in_process_backend(monkeypatch) -> None:
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")


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
    run_id: str | None = None,
    time_limit_seconds: float | None = None,
) -> dict:
    wire = {
        WIRE_STORAGE_ROOT: str(tmp_path.resolve()),
        "gameId": sample_turn.game.id,
        "perspective": sample_turn.player.id,
        "turn": sample_turn.settings.turn,
        "playerId": player_id,
        WIRE_LADDER_STATE: process_safe_ladder_state(ladder),
        WIRE_OBSERVATION: observation,
        WIRE_TIME_LIMIT_SECONDS: (
            stream_tier_time_limit_seconds() if time_limit_seconds is None else time_limit_seconds
        ),
    }
    if run_id is not None:
        wire[WIRE_RUN_ID] = run_id
    return wire


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
    assert resolve_scores_tier_solve_backend() == "thread"


def test_resolve_scores_tier_solve_backend_env_process(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    assert resolve_scores_tier_solve_backend() == "process"


def test_resolve_scores_tier_solve_backend_frozen_honors_process_env(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: True)
    assert resolve_scores_tier_solve_backend() == "process"


def test_resolve_scores_step_backend_remaps_only_tier_solve(monkeypatch):
    from api.analytics.scores.compute_orchestration import (
        SCORES_MATERIALIZE,
        SCORES_TIER_SOLVE,
        resolve_scores_step_backend,
    )

    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    assert resolve_scores_step_backend(SCORES_TIER_SOLVE, "thread") == "process"
    assert resolve_scores_step_backend(SCORES_MATERIALIZE, "inline") == "inline"


def test_open_evidence_thread_wire_is_identity_without_process_rebuild_keys(
    sample_turn,
    monkeypatch,
) -> None:
    monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    player_id = inference_target_player_id(sample_turn)
    run = _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    with patch(
        "api.analytics.scores.compute_orchestration._process_safe_tier_solve_job_wire"
    ) as fat_wire:
        wire = build_scores_tier_solve_job_wire(
            _scores_scope(sample_turn, player_id),
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
    fat_wire.assert_not_called()
    assert set(wire) == _THREAD_IDENTITY_KEYS
    assert wire[WIRE_RUN_ID] == run.run_id
    assert not _PROCESS_REBUILD_KEYS & set(wire)


def test_open_evidence_process_wire_is_storage_rebuild_snapshot(
    sample_turn,
    tmp_path,
    monkeypatch,
) -> None:
    _opt_in_process_backend(monkeypatch)
    player_id = inference_target_player_id(sample_turn)
    run = _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert wire[WIRE_RUN_ID] == run.run_id
    assert _PROCESS_REBUILD_KEYS <= set(wire)
    assert isinstance(wire[WIRE_STORAGE_ROOT], str)
    assert isinstance(wire[WIRE_LADDER_STATE], PolicyLadderState)
    assert wire[WIRE_LADDER_STATE].catalog is None
    assert wire[WIRE_LADDER_STATE].problem is None
    assert wire[WIRE_OBSERVATION] is not None
    pickle.dumps(wire)
    leaf_wire = dict(wire)
    leaf_wire[WIRE_STORAGE_ROOT] = str(_put_turn_tree(tmp_path, sample_turn).resolve())
    snapshot = run_scores_tier_solve_leaf(leaf_wire)
    assert isinstance(snapshot, dict)
    assert snapshot[WIRE_RUN_ID] == run.run_id
    assert isinstance(snapshot.get(WIRE_LADDER_STATE), PolicyLadderState)
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome in {"continue", "persist", "waiting_deps"}
    assert coerce_step_result(snapshot).outcome == "persist"


def test_open_evidence_frozen_process_env_uses_storage_rebuild_wire(
    sample_turn,
    monkeypatch,
) -> None:
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: True)
    player_id = inference_target_player_id(sample_turn)
    _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert _PROCESS_REBUILD_KEYS <= set(wire)


def test_orchestration_skip_stays_off_the_process_pool():
    skip = {
        "runId": None,
        WIRE_EVIDENCE_CLOSED: True,
        WIRE_ORCHESTRATION_SKIP: True,
    }
    result = orchestration_plane_skip_result(skip)
    assert result is not None
    assert result.outcome == "complete"
    assert orchestration_plane_skip_result({"runId": "live"}) is None
    with pytest.raises(RuntimeError, match="orchestration plane"):
        run_scores_tier_solve_leaf(skip)


def test_open_file_backend_does_not_create_missing_root(tmp_path) -> None:
    missing = tmp_path / "absent-store"
    assert not missing.exists()
    storage = open_file_backend(missing)
    assert not missing.exists()
    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/111")
    assert not missing.exists()


def test_leaf_missing_storage_root_fails_without_creating_directories(
    sample_turn,
    tmp_path,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = build_inference_observation(score, sample_turn)
    missing = tmp_path / "absent-store"
    assert not missing.exists()
    with pytest.raises(NotFoundError):
        run_scores_tier_solve_leaf(
            _leaf_wire(
                tmp_path=missing,
                sample_turn=sample_turn,
                player_id=player_id,
                observation=observation,
                ladder=PolicyLadderState(policy_steps=(_tiny_policy_step(),)),
            )
        )
    assert not missing.exists()


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
    snapshot = result[WIRE_LADDER_STATE]
    assert isinstance(snapshot, PolicyLadderState)
    assert in_process.ladder_complete is True
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
    snapshot = result[WIRE_LADDER_STATE]
    assert isinstance(snapshot, PolicyLadderState)
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
    snapshot = result[WIRE_LADDER_STATE]
    assert isinstance(snapshot, PolicyLadderState)
    assert snapshot.last_status == expected.status


def test_continue_payload_advances_parent_ladder_without_child_rowrun(
    sample_turn,
    tmp_path,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = replace(
        build_inference_observation(score, sample_turn),
        military_delta_2x=1,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
    )
    steps = (_tiny_policy_step("a", max_seconds=0.0), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    assert parent.ladder_state is not None
    assert parent.ladder_state.next_step_index == 0

    snapshot = run_scores_tier_solve_leaf(
        _leaf_wire(
            tmp_path=_put_turn_tree(tmp_path, sample_turn),
            sample_turn=sample_turn,
            player_id=player_id,
            observation=observation,
            ladder=PolicyLadderState(policy_steps=steps),
            run_id=parent.run_id,
            time_limit_seconds=0.0,
        )
    )
    assert snapshot[WIRE_RUN_ID] == parent.run_id
    scope = _scores_scope(sample_turn, player_id)
    mapped = map_scores_tier_solve_remote_result(scope, snapshot)
    assert mapped.outcome == "continue"
    assert parent.ladder_state is not None
    assert parent.ladder_state.next_step_index == 1
    assert parent.ladder_state.ladder_complete is False
    ctx = _open_evidence_ctx(sample_turn)
    build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
        node_result_wire=mapped.payload,
    )
    assert parent.ladder_state.next_step_index == 1
    assert parent.ladder_state.ladder_complete is False


def test_apply_helper_accepts_step_result_or_payload_dict(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    apply_scores_tier_solve_step_result(
        parent,
        StepResult(outcome="continue", payload={WIRE_LADDER_STATE: continued}),
    )
    assert parent.ladder_state is continued
    completed = PolicyLadderState(policy_steps=steps, ladder_complete=True)
    apply_scores_tier_solve_step_result(parent, {WIRE_LADDER_STATE: completed})
    assert parent.ladder_state is completed


@pytest.mark.parametrize("backend", ["thread", "process"])
def test_wire_build_applies_continue_snapshot_before_next_dispatch(
    sample_turn,
    monkeypatch,
    backend: str,
) -> None:
    if backend == "process":
        _opt_in_process_backend(monkeypatch)
    else:
        monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
        node_result_wire={
            WIRE_RUN_ID: parent.run_id,
            WIRE_LADDER_STATE: continued,
        },
    )
    assert parent.ladder_state is continued
    assert parent.ladder_state.next_step_index == 1
    assert wire[WIRE_RUN_ID] == parent.run_id
    if backend == "process":
        assert wire[WIRE_LADDER_STATE].next_step_index == 1
    else:
        assert WIRE_LADDER_STATE not in wire


def test_persist_without_run_id_fails_even_when_scope_has_row_run(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(sample_turn, player_id=player_id)
    scope = _scores_scope(sample_turn, player_id)
    ctx = _open_evidence_ctx(sample_turn)
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="missing runId",
    )
    with pytest.raises(TypeError, match="missing string runId"):
        ScoresPersistencePolicy().persist(ctx, scope, {"rowComplete": row_complete})
    assert get_row_run_for_scope(scope) is parent


def test_persist_echoed_run_id_applies_ladder_and_writes(
    sample_turn,
    memory_backend,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    snapshot = PolicyLadderState(policy_steps=(), ladder_complete=True)
    row_persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(persistence=row_persistence),
        },
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="echoed runId persist",
    )
    ScoresPersistencePolicy().persist(
        ctx,
        _scores_scope(sample_turn, player_id),
        {
            WIRE_RUN_ID: parent.run_id,
            WIRE_LADDER_STATE: snapshot,
            "rowComplete": row_complete,
        },
    )
    assert parent.ladder_state is snapshot
    stored = row_persistence.get_row(
        sample_turn.game.id,
        sample_turn.player.id,
        sample_turn.settings.turn,
        player_id,
    )
    assert stored is not None
    assert stored.summary == "echoed runId persist"


def test_leaf_echoes_job_wire_run_id_on_snapshot(sample_turn, tmp_path) -> None:
    player_id = inference_target_player_id(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    observation = build_inference_observation(score, sample_turn)
    snapshot = run_scores_tier_solve_leaf(
        _leaf_wire(
            tmp_path=_put_turn_tree(tmp_path, sample_turn),
            sample_turn=sample_turn,
            player_id=player_id,
            observation=observation,
            ladder=PolicyLadderState(policy_steps=(_tiny_policy_step(),)),
            run_id="echo-run",
        )
    )
    assert snapshot[WIRE_RUN_ID] == "echo-run"
    assert isinstance(snapshot.get(WIRE_LADDER_STATE), PolicyLadderState)
    assert "outcome" not in snapshot


def test_leaf_module_does_not_map_orchestrator_outcomes() -> None:
    import api.analytics.scores.compute_plane.tier_solve_leaf as leaf

    source = Path(leaf.__file__).read_text()
    forbidden = (
        "finalize_policy_ladder_result",
        "row_complete_from_ladder_finalize",
        "is_durable_turn_evidence_row_status",
        "fleet_torp_input_status_diagnostics",
        "_step_result_from_ladder_state",
    )
    for name in forbidden:
        assert name not in source, name


def test_parent_mapper_continue_from_incomplete_leaf_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    snapshot = {WIRE_RUN_ID: parent.run_id, WIRE_LADDER_STATE: continued}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "continue"
    assert parent.ladder_state is continued
    assert mapped.payload[WIRE_RUN_ID] == parent.run_id
    assert coerce_step_result(snapshot).outcome == "persist"


def test_parent_mapper_persist_from_complete_leaf_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    completed = PolicyLadderState(policy_steps=(), ladder_complete=True)
    snapshot = {WIRE_RUN_ID: parent.run_id, WIRE_LADDER_STATE: completed}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "persist"
    assert parent.ladder_state is completed
    assert isinstance(mapped.payload, dict)
    assert mapped.payload[WIRE_RUN_ID] == parent.run_id
    assert mapped.payload["rowComplete"] is not None


def test_parent_mapper_soft_defers_missing_ladder_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(sample_turn, player_id=player_id)
    snapshot = {WIRE_RUN_ID: parent.run_id}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "waiting_deps"
    assert mapped.wait_recovery is None


def test_parent_mapper_uses_parent_row_run_for_ladder_complete(sample_turn) -> None:
    from api.analytics.military_score_inference.inference_row_runner import (
        outcome_after_ladder_complete,
    )

    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    parent.session.fleet_torp_input_status = "applied"
    captured: dict[str, object] = {}

    def spy(run, state, observation, turn):
        captured["run"] = run
        captured["fleet_torp"] = run.session.fleet_torp_input_status
        return outcome_after_ladder_complete(run, state, observation, turn)

    snapshot = {
        WIRE_RUN_ID: parent.run_id,
        WIRE_LADDER_STATE: PolicyLadderState(policy_steps=(), ladder_complete=True),
    }
    with patch(
        "api.analytics.scores.compute_orchestration.outcome_after_ladder_complete",
        spy,
    ):
        mapped = map_scores_tier_solve_remote_result(
            _scores_scope(sample_turn, player_id),
            snapshot,
        )
    assert captured["run"] is parent
    assert captured["fleet_torp"] == "applied"
    assert mapped.outcome == "persist"
