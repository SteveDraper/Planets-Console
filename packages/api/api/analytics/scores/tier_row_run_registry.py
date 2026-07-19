"""Scores instance of the generic table-stream row-run shell + admission pattern.

Owns scores ``RowRun`` shells and compact persist admission. Types
(``RowRunPhase``, ``PersistAdmission``) are generic stream-row vocabulary from
:mod:`api.streaming.table_stream.row_run_admission` -- not scores-private.

Retained shells use ``RowRunPhase`` (``REGISTERED`` / ``DETACHED`` only).
Cancel intent drops the shell immediately and records compact cancelled
admission keyed by scores scope so ``PersistAdmission.CANCEL_DENY`` still
denies late persist. A later ``REGISTERED`` for the same scope supersedes
that cancelled admission (preempt / re-adopt). Memory is O(scopes with an
outstanding cancel), not an unbounded UUID FIFO.

Production persist writers use :func:`api.analytics.scores.persist_decision.decide_scores_row_persist`
(``PersistDecision``) -- not :func:`get_persist_admission` directly.
"""

from __future__ import annotations

import threading

from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.compute.scope import WILDCARD, ComputeScope
from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

_lock = threading.Lock()
# REGISTERED and DETACHED shells only -- cancel never retains a shell.
_runs_by_id: dict[str, RowRun] = {}
_run_id_by_scope_key: dict[tuple[int, int, int, int], str] = {}
_tier_callbacks_by_run_id: dict[str, InferenceTierJobCallbacks] = {}
# Compact cancelled admission: at most one run_id per scores scope.
_cancelled_admissions: dict[str, tuple[int, int, int, int]] = {}
_cancelled_run_by_scope: dict[tuple[int, int, int, int], str] = {}


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


def _drop_shell_locked(run_id: str) -> RowRun | None:
    """Remove retained shell and indexes. Caller holds ``_lock``."""
    run = _runs_by_id.pop(run_id, None)
    if run is None:
        return None
    _clear_scope_index_locked(run)
    _tier_callbacks_by_run_id.pop(run_id, None)
    return run


def _forget_cancelled_locked(run_id: str) -> None:
    """Drop compact cancelled admission for ``run_id``. Caller holds ``_lock``."""
    scope_key = _cancelled_admissions.pop(run_id, None)
    if scope_key is not None and _cancelled_run_by_scope.get(scope_key) == run_id:
        _cancelled_run_by_scope.pop(scope_key, None)


def _supersede_cancelled_for_scope_locked(scope_key: tuple[int, int, int, int]) -> None:
    """Clear any cancelled admission for ``scope_key``. Caller holds ``_lock``."""
    prior = _cancelled_run_by_scope.pop(scope_key, None)
    if prior is not None:
        _cancelled_admissions.pop(prior, None)


def _record_cancelled_locked(run_id: str, scope_key: tuple[int, int, int, int]) -> None:
    """Remember cancelled admission for ``run_id`` under ``scope_key``. Caller holds ``_lock``."""
    _forget_cancelled_locked(run_id)
    _supersede_cancelled_for_scope_locked(scope_key)
    _cancelled_admissions[run_id] = scope_key
    _cancelled_run_by_scope[scope_key] = run_id


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
    scope_key = _session_scope_key(run.session)
    with _lock:
        # Same-scope re-register supersedes prior cancelled admission (preempt path).
        _supersede_cancelled_for_scope_locked(scope_key)
        _forget_cancelled_locked(run.run_id)
        _runs_by_id[run.run_id] = run
        _run_id_by_scope_key[scope_key] = run.run_id


def get_row_run(run_id: str) -> RowRun | None:
    """Return a retained REGISTERED or DETACHED shell, if any."""
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
    """Retained shell phase only (``REGISTERED`` / ``DETACHED``); never admission."""
    with _lock:
        run = _runs_by_id.get(run_id)
        return None if run is None else run.phase


def get_persist_admission(run_id: str) -> PersistAdmission:
    """Registry-internal admission lookup (shell vs compact cancel vs absent).

    Not a production persist gate. Public callers use
    :func:`api.analytics.scores.persist_decision.decide_scores_row_persist`
    (``PersistDecision``). This probe exists for that mapper and registry tests.
    """
    with _lock:
        if run_id in _runs_by_id:
            return PersistAdmission.ALLOW
        if run_id in _cancelled_admissions:
            return PersistAdmission.CANCEL_DENY
        return PersistAdmission.ABSENT


def has_cancelled_admission(run_id: str) -> bool:
    """True when compact cancelled-admission memory still holds ``run_id``."""
    with _lock:
        return run_id in _cancelled_admissions


def detach_row_run(run_id: str) -> None:
    """Transition ``REGISTERED`` → ``DETACHED``; clear scope index; keep by id.

    Detach must not destroy admission state: late persist still finds the shell.
    No-op when missing or already cancelled (compact). ``DETACHED`` stays ``DETACHED``.
    """
    with _lock:
        if run_id in _cancelled_admissions:
            return
        run = _runs_by_id.get(run_id)
        if run is None:
            return
        run.phase = RowRunPhase.DETACHED
        _clear_scope_index_locked(run)
        _tier_callbacks_by_run_id.pop(run_id, None)


def mark_row_run_cancelled(run_id: str) -> RowRun | None:
    """Record cancelled admission; drop any shell; return the dropped shell if any.

    Compact cancelled memory is scope-keyed (one outstanding cancel per scores
    scope). The dropped shell is not painted with a cancel phase -- cancel is
    admission memory only. Caller still cancels the session token and seals
    stream cancel (``CANCELED`` + drain closed) via
    :func:`api.analytics.scores.cancel_intent.apply_scores_row_cancel`.
    """
    with _lock:
        dropped = _drop_shell_locked(run_id)
        if dropped is not None:
            _record_cancelled_locked(run_id, _session_scope_key(dropped.session))
            return dropped
        # Already compact-cancelled (or never registered): leave admission as-is.
        return None


def retire_row_run(run_id: str) -> None:
    """Drop registry shell and cancelled-admission memory after persist or retire."""
    with _lock:
        _forget_cancelled_locked(run_id)
        _drop_shell_locked(run_id)


def unregister_row_run(run_id: str) -> None:
    """Drop registry entries (retire). Prefer :func:`detach_row_run` for stream detach."""
    retire_row_run(run_id)


def clear_row_runs() -> None:
    """Drop every retained RowRun and cancelled admission (full invalidate / shutdown)."""
    with _lock:
        _runs_by_id.clear()
        _run_id_by_scope_key.clear()
        _tier_callbacks_by_run_id.clear()
        _cancelled_admissions.clear()
        _cancelled_run_by_scope.clear()


def register_tier_callbacks(run_id: str, callbacks: InferenceTierJobCallbacks) -> None:
    with _lock:
        _tier_callbacks_by_run_id[run_id] = callbacks


def get_tier_callbacks(run_id: str) -> InferenceTierJobCallbacks | None:
    with _lock:
        return _tier_callbacks_by_run_id.get(run_id)


def reset_tier_row_run_registry_for_tests() -> None:
    clear_row_runs()
