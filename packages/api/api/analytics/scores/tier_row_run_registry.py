"""Registry for scores tier_solve RowRun state between orchestrator continuations."""

from __future__ import annotations

import threading

from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.scores.cancel_fence_store import is_run_cancel_fenced
from api.analytics.scores.known_run_allow_store import record_known_run_allow
from api.compute.scope import WILDCARD, ComputeScope

_lock = threading.Lock()
_runs_by_id: dict[str, RowRun] = {}
_run_id_by_scope_key: dict[tuple[int, int, int, int], str] = {}
_tier_callbacks_by_run_id: dict[str, InferenceTierJobCallbacks] = {}


def _scope_key(scope: ComputeScope) -> tuple[int, int, int, int]:
    if scope.perspective == WILDCARD or not isinstance(scope.perspective, int):
        raise ValueError("scores tier scope requires concrete perspective")
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        raise ValueError("scores tier scope requires concrete turn")
    if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
        raise ValueError("scores tier scope requires concrete player_id")
    return (scope.game_id, scope.perspective, scope.turn, scope.player_id)


def _session_scope_key(session) -> tuple[int, int, int, int]:
    return (
        session.game_id,
        session.perspective,
        session.turn_number,
        session.player_id,
    )


def initialize_tier_ladder_state(
    run: RowRun,
    *,
    orchestration: InferenceStreamOrchestration | None = None,
) -> None:
    """Initialize ladder state for one registered scores tier row run."""
    session = run.session
    run.orchestration = orchestration
    if orchestration is not None:
        run.ladder_state = orchestration.new_ladder_state(
            resolved_mask=session.resolved_mask,
            fleet_torp_overlay=session.fleet_torp_overlay,
            prior_fleet_max_tech_by_axis=session.prior_fleet_max_tech_by_axis,
        )
        return
    policy_steps = tuple(resolve_tier_policies(None))
    run.ladder_state = PolicyLadderState(
        policy_steps=policy_steps,
        resolved_mask=session.resolved_mask,
        fleet_torp_overlay=session.fleet_torp_overlay,
        prior_fleet_max_tech_by_axis=session.prior_fleet_max_tech_by_axis,
    )


def register_row_run(
    run: RowRun,
    *,
    orchestration: InferenceStreamOrchestration | None = None,
    initialize_ladder: bool = True,
) -> None:
    """Register one RowRun for orchestrator tier_solve wire build and execution."""
    if initialize_ladder and run.ladder_state is None:
        initialize_tier_ladder_state(run, orchestration=orchestration)
    with _lock:
        _runs_by_id[run.run_id] = run
        _run_id_by_scope_key[_session_scope_key(run.session)] = run.run_id


def get_row_run(run_id: str) -> RowRun | None:
    with _lock:
        return _runs_by_id.get(run_id)


def get_row_run_for_scope(scope: ComputeScope) -> RowRun | None:
    with _lock:
        run_id = _run_id_by_scope_key.get(_scope_key(scope))
        if run_id is None:
            return None
        return _runs_by_id.get(run_id)


def is_row_run_cancelled(run_id: str) -> bool:
    """True when ``run_id`` has a generation-scoped cancel fence.

    Prefer :func:`api.analytics.scores.persist_decision.decide_scores_row_persist`
    for persist admission. Kept for cancel/detach tests that assert the fence.
    """
    return is_run_cancel_fenced(run_id)


def unregister_row_run(run_id: str) -> None:
    """Drop registry entries and record a known-run allow when not cancel-fenced.

    Cancel already wrote a generation fence before this call. Detach does not;
    the known-run allow is the positive finish-after-detach persist signal.
    """
    with _lock:
        run = _runs_by_id.pop(run_id, None)
        if run is None:
            return
        scope_key = _session_scope_key(run.session)
        if _run_id_by_scope_key.get(scope_key) == run_id:
            _run_id_by_scope_key.pop(scope_key, None)
        _tier_callbacks_by_run_id.pop(run_id, None)
    if not is_run_cancel_fenced(run_id):
        record_known_run_allow(run_id)


def register_tier_callbacks(run_id: str, callbacks: InferenceTierJobCallbacks) -> None:
    with _lock:
        _tier_callbacks_by_run_id[run_id] = callbacks


def get_tier_callbacks(run_id: str) -> InferenceTierJobCallbacks | None:
    with _lock:
        return _tier_callbacks_by_run_id.get(run_id)


def reset_tier_row_run_registry_for_tests() -> None:
    with _lock:
        _runs_by_id.clear()
        _run_id_by_scope_key.clear()
        _tier_callbacks_by_run_id.clear()
