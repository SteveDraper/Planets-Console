"""Single owner for scores tier_solve RowRun state and persist-admission phase."""

from __future__ import annotations

import threading
from collections import OrderedDict

from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun, RowRunPhase
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.compute.scope import WILDCARD, ComputeScope

# CANCELLED shells are FIFO-bounded so unique run UUIDs cannot retain RowRun
# objects without limit. Same capacity class as ``MAX_STREAM_RESOLUTIONS`` and
# the former ``MAX_CANCEL_FENCE_RUN_IDS`` (4096). Shell eviction remembers the
# run_id in a compact denial set (also bounded) so late persist still
# ``DENY_CANCEL`` rather than ``REFUSE_UNKNOWN``.
MAX_CANCELLED_ROW_RUNS = 4096

_lock = threading.Lock()
_runs_by_id: dict[str, RowRun] = {}
_run_id_by_scope_key: dict[tuple[int, int, int, int], str] = {}
_tier_callbacks_by_run_id: dict[str, InferenceTierJobCallbacks] = {}
# Insertion order among retained CANCELLED shells; eviction drops the shell.
_cancelled_shell_fifo: OrderedDict[str, None] = OrderedDict()
# Compact memory after shell eviction; persist still DENY_CANCEL.
_evicted_cancelled_run_ids: OrderedDict[str, None] = OrderedDict()


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


def _clear_scope_index_locked(run: RowRun) -> None:
    scope_key = _session_scope_key(run.session)
    if _run_id_by_scope_key.get(scope_key) == run.run_id:
        _run_id_by_scope_key.pop(scope_key, None)


def _drop_shell_locked(run_id: str) -> None:
    """Remove retained shell and indexes. Caller holds ``_lock``."""
    run = _runs_by_id.pop(run_id, None)
    if run is None:
        return
    _clear_scope_index_locked(run)
    _tier_callbacks_by_run_id.pop(run_id, None)


def _trim_cancelled_locked() -> None:
    """Bound CANCELLED shells then compact denial ids. Caller holds ``_lock``."""
    while len(_cancelled_shell_fifo) > MAX_CANCELLED_ROW_RUNS:
        old_id, _ = _cancelled_shell_fifo.popitem(last=False)
        _drop_shell_locked(old_id)
        _evicted_cancelled_run_ids.pop(old_id, None)
        _evicted_cancelled_run_ids[old_id] = None
    while len(_evicted_cancelled_run_ids) > MAX_CANCELLED_ROW_RUNS:
        _evicted_cancelled_run_ids.popitem(last=False)


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
    run.phase = RowRunPhase.REGISTERED
    with _lock:
        _cancelled_shell_fifo.pop(run.run_id, None)
        _evicted_cancelled_run_ids.pop(run.run_id, None)
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
        run = _runs_by_id.get(run_id)
        if run is None or run.phase is not RowRunPhase.REGISTERED:
            return None
        return run


def get_row_run_phase(run_id: str) -> RowRunPhase | None:
    with _lock:
        run = _runs_by_id.get(run_id)
        return None if run is None else run.phase


def is_row_run_cancelled(run_id: str) -> bool:
    """True when ``run_id`` is retained in ``CANCELLED`` phase.

    Prefer :func:`api.analytics.scores.persist_decision.decide_scores_row_persist`
    for persist admission (also covers shell-evicted cancel denial memory).
    """
    return get_row_run_phase(run_id) is RowRunPhase.CANCELLED


def is_evicted_cancelled_run(run_id: str) -> bool:
    """True when a CANCELLED shell was FIFO-evicted but denial memory remains."""
    with _lock:
        return run_id in _evicted_cancelled_run_ids


def detach_row_run(run_id: str) -> None:
    """Transition ``REGISTERED`` → ``DETACHED``; clear scope index; keep by id.

    Detach must not destroy admission state: late persist still finds the shell.
    No-op when missing or already ``CANCELLED``. ``DETACHED`` stays ``DETACHED``.
    """
    with _lock:
        run = _runs_by_id.get(run_id)
        if run is None:
            return
        if run.phase is RowRunPhase.CANCELLED:
            return
        run.phase = RowRunPhase.DETACHED
        _clear_scope_index_locked(run)
        _tier_callbacks_by_run_id.pop(run_id, None)


def mark_row_run_cancelled(run_id: str) -> None:
    """Transition to ``CANCELLED``; clear scope index; keep by id for late DENY.

    CANCELLED shells are FIFO-bounded by ``MAX_CANCELLED_ROW_RUNS``. Evicted
    shells leave a compact run_id in denial memory so persist still
    ``DENY_CANCEL``. Replaces generation-scoped cancel fences for persist
    admission. Caller still cancels the session token and sets stream-resolution
    ``CANCELED`` (delivery).
    """
    with _lock:
        run = _runs_by_id.get(run_id)
        if run is None:
            return
        run.phase = RowRunPhase.CANCELLED
        _clear_scope_index_locked(run)
        _tier_callbacks_by_run_id.pop(run_id, None)
        _evicted_cancelled_run_ids.pop(run_id, None)
        _cancelled_shell_fifo.pop(run_id, None)
        _cancelled_shell_fifo[run_id] = None
        _trim_cancelled_locked()


def retire_row_run(run_id: str) -> None:
    """Drop registry entries after persist decision or explicit retire."""
    with _lock:
        _cancelled_shell_fifo.pop(run_id, None)
        _evicted_cancelled_run_ids.pop(run_id, None)
        _drop_shell_locked(run_id)


def unregister_row_run(run_id: str) -> None:
    """Drop registry entries (retire). Prefer :func:`detach_row_run` for stream detach."""
    retire_row_run(run_id)


def clear_row_runs() -> None:
    """Drop every retained RowRun (full invalidate / shutdown)."""
    with _lock:
        _runs_by_id.clear()
        _run_id_by_scope_key.clear()
        _tier_callbacks_by_run_id.clear()
        _cancelled_shell_fifo.clear()
        _evicted_cancelled_run_ids.clear()


def register_tier_callbacks(run_id: str, callbacks: InferenceTierJobCallbacks) -> None:
    with _lock:
        _tier_callbacks_by_run_id[run_id] = callbacks


def get_tier_callbacks(run_id: str) -> InferenceTierJobCallbacks | None:
    with _lock:
        return _tier_callbacks_by_run_id.get(run_id)


def reset_tier_row_run_registry_for_tests() -> None:
    clear_row_runs()
