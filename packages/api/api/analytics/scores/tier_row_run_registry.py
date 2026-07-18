"""Registry for scores tier_solve RowRun state between orchestrator continuations."""

from __future__ import annotations

import threading
from collections import OrderedDict

from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.compute.scope import WILDCARD, ComputeScope

# Explicit cancellation fences persist after ``unregister_row_run`` so
# ``ScoresPersistencePolicy`` can refuse cancel-after-unregister races. Detach
# must not set a fence. Run IDs are unique UUIDs, so fences are FIFO-bounded by
# ``MAX_CANCEL_FENCE_RUN_IDS`` rather than kept for process lifetime; the race
# window a late persist must lose to is short relative to this capacity.
MAX_CANCEL_FENCE_RUN_IDS = 4096

_lock = threading.Lock()
_runs_by_id: dict[str, RowRun] = {}
_run_id_by_scope_key: dict[tuple[int, int, int, int], str] = {}
_tier_callbacks_by_run_id: dict[str, InferenceTierJobCallbacks] = {}
_cancel_fence_run_ids: OrderedDict[str, None] = OrderedDict()


def _trim_cancel_fence_run_ids() -> None:
    """Evict oldest cancel fences until at capacity. Caller holds ``_lock``."""
    while len(_cancel_fence_run_ids) > MAX_CANCEL_FENCE_RUN_IDS:
        _cancel_fence_run_ids.popitem(last=False)


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


def mark_row_run_cancelled(run_id: str) -> None:
    """Set an explicit cancellation fence that survives RowRun unregister.

    Production cancel goes through
    ``InferenceStreamTeardownMixin._apply_cancel_intent_locked``, which sets
    this fence together with the cancel token and stream-resolution CANCELED.
    Call this directly only for fence-capacity tests. Detach must not set a
    fence -- detached workers may still persist from the RowComplete payload.

    Fences are FIFO-bounded by ``MAX_CANCEL_FENCE_RUN_IDS`` (accepted capacity;
    late-persist races are short relative to it). Re-marking the same
    ``run_id`` refreshes its eviction order. Always call before
    ``unregister_row_run``.
    """
    with _lock:
        _cancel_fence_run_ids.pop(run_id, None)
        _cancel_fence_run_ids[run_id] = None
        _trim_cancel_fence_run_ids()


def is_row_run_cancelled(run_id: str) -> bool:
    """True when an explicit cancellation fence was set for ``run_id``."""
    with _lock:
        return run_id in _cancel_fence_run_ids


def unregister_row_run(run_id: str) -> None:
    with _lock:
        run = _runs_by_id.pop(run_id, None)
        if run is None:
            return
        scope_key = _session_scope_key(run.session)
        if _run_id_by_scope_key.get(scope_key) == run_id:
            _run_id_by_scope_key.pop(scope_key, None)
        _tier_callbacks_by_run_id.pop(run_id, None)


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
        _cancel_fence_run_ids.clear()
