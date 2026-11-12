"""Scores instance of the generic table-stream row-run shell + admission pattern.

Owns scores ``RowRun`` shells and compact persist admission. Types
(``RowRunPhase``, ``PersistAdmission``) are generic stream-row vocabulary from
:mod:`api.streaming.table_stream.row_run_admission` -- not scores-private.

Retained shells use ``RowRunPhase`` (``REGISTERED`` / ``DETACHED`` only).
Cancel drops the shell immediately and records compact cancelled admission
keyed by scores scope so ``PersistAdmission.CANCEL_DENY`` still denies late
persist. A later ``REGISTERED`` for the same scope supersedes that cancelled
admission (preempt / re-adopt). Memory is O(scopes with an outstanding
cancel), not an unbounded UUID FIFO.

Lifecycle matrix sides (detach / cancel / retire) are applied by
:func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`.
Production persist writers use :func:`decide_scores_row_persist` (admission +
phase under one lock) -- not :func:`get_persist_admission` directly.

Tier ladder resume and hand-over. Each ``tier_solve`` wire build claims the
scope's ladder through :func:`claim_tier_ladder`, one atomic registry
operation that chooses the RowRun, hands the ladder over, retires the scope's
other runs and writes the scope's :class:`TierLadderStamp`: the RowRun whose
ladder serves the scores node, the node's execution generation and the scores
epoch. Detach clears the scope index but keeps the stamp, so the next
continuation of the same node resumes its own ``DETACHED`` RowRun instead of
restarting the ladder. The stamp is guarded on read: a node replacement or a
scores epoch change retires the ``DETACHED`` shell and the caller takes the
admit path.

The scope index names the run a claim stamps. Its registering caller decides
whether a run takes it (:class:`ScopeIndexPolicy`): a stream's run always
does, and a background run only when no ``REGISTERED`` run holds it, so a
background run registered after a stream's run never displaces it and is
retired at the next claim instead.

When a different RowRun holds the scope index (a reopened stream's run, or a
stream's run at a hop a walk's background run was solving), the claim hands
the unfinished ladder over: the stamped run's ``ladder_state`` and
``orchestration`` move to the new run while the stamp still serves this node
execution and scores epoch. Every other ``REGISTERED`` or ``DETACHED`` run for
the scope is retired, and their ids are returned so the scheduler forgets
them. A stamp is also released when its shell is dropped (retire-after-write,
cancel, retire) and when the scores node reaches terminal
(:func:`release_tier_ladder_for_scope`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from api.analytics.fleet.counterparty_ledger import counterparty_fleet_loader
from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    new_ladder_state,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.persist_decision import (
    PersistDecision,
    persist_decision_from_admission,
)
from api.compute.scope import WILDCARD, ComputeScope
from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

type ScoresScopeKey = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TierLadderStamp:
    """The RowRun whose ladder serves one scores node execution at one scores epoch."""

    run_id: str
    execution_generation: int
    scores_epoch: int

    def serves(self, *, execution_generation: int, scores_epoch: int) -> bool:
        return (self.execution_generation, self.scores_epoch) == (
            execution_generation,
            scores_epoch,
        )


class ScopeIndexPolicy(Enum):
    """Whether a RowRun being registered becomes its scope's indexed run.

    The registering caller decides; the registry applies it under its lock.
    """

    # The run takes the scope index, replacing any run indexed there.
    TAKE = "take"
    # The run takes the scope index only when no REGISTERED run holds it.
    TAKE_IF_VACANT = "take_if_vacant"


@dataclass(frozen=True, slots=True)
class LadderClaim:
    """The RowRun stamped to serve a scope's ladder, and what the claim did to the others.

    ``retired_run_ids`` names every other run for the scope, now retired; the
    scheduler forgets them. ``ladder_handed_over`` is true when ``run`` took
    over another run's unfinished ladder, so its stream has not yet seen that
    ladder's held solutions.
    """

    run: RowRun
    retired_run_ids: tuple[str, ...]
    ladder_handed_over: bool


_lock = threading.Lock()
# REGISTERED and DETACHED shells only -- cancel never retains a shell.
_runs_by_id: dict[str, RowRun] = {}
_run_id_by_scope_key: dict[ScoresScopeKey, str] = {}
_tier_callbacks_by_run_id: dict[str, InferenceTierJobCallbacks] = {}
# Compact cancelled admission: at most one run_id per scores scope.
_cancelled_admissions: dict[str, ScoresScopeKey] = {}
_cancelled_run_by_scope: dict[ScoresScopeKey, str] = {}
# One tier ladder per scores scope; its shell is always retained.
_ladder_stamp_by_scope_key: dict[ScoresScopeKey, TierLadderStamp] = {}


def _scope_key(scope: ComputeScope) -> ScoresScopeKey:
    if scope.perspective == WILDCARD or not isinstance(scope.perspective, int):
        raise ValueError("scores tier scope requires concrete perspective")
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        raise ValueError("scores tier scope requires concrete turn")
    if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
        raise ValueError("scores tier scope requires concrete player_id")
    return (scope.game_id, scope.perspective, scope.turn, scope.player_id)


def _session_scope_key(session) -> ScoresScopeKey:
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
    scope_key = _session_scope_key(run.session)
    stamp = _ladder_stamp_by_scope_key.get(scope_key)
    if stamp is not None and stamp.run_id == run_id:
        _ladder_stamp_by_scope_key.pop(scope_key, None)
    return run


def _retire_row_run_locked(run_id: str) -> None:
    """RETIRE side: drop the shell and clear admission. Caller holds ``_lock``."""
    _forget_cancelled_locked(run_id)
    _drop_shell_locked(run_id)


def _release_ladder_stamp_locked(scope_key: ScoresScopeKey) -> None:
    """Drop the scope's ladder stamp and retire its shell when no stream owns it.

    A ``REGISTERED`` shell stays: its stream retires it at finalize. Caller
    holds ``_lock``.
    """
    stamp = _ladder_stamp_by_scope_key.pop(scope_key, None)
    if stamp is None:
        return
    run = _runs_by_id.get(stamp.run_id)
    if run is not None and run.phase is RowRunPhase.DETACHED:
        _retire_row_run_locked(stamp.run_id)


def _forget_cancelled_locked(run_id: str) -> None:
    """Drop compact cancelled admission for ``run_id``. Caller holds ``_lock``."""
    scope_key = _cancelled_admissions.pop(run_id, None)
    if scope_key is not None and _cancelled_run_by_scope.get(scope_key) == run_id:
        _cancelled_run_by_scope.pop(scope_key, None)


def _supersede_cancelled_for_scope_locked(scope_key: ScoresScopeKey) -> None:
    """Clear any cancelled admission for ``scope_key``. Caller holds ``_lock``."""
    prior = _cancelled_run_by_scope.pop(scope_key, None)
    if prior is not None:
        _cancelled_admissions.pop(prior, None)


def _record_cancelled_locked(run_id: str, scope_key: ScoresScopeKey) -> None:
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
    run.ladder_state = new_ladder_state(
        session,
        load_counterparty_fleet=counterparty_fleet_loader(
            session.query_context,
            game_id=session.game_id,
            perspective=session.perspective,
            turn_number=session.turn_number,
        ),
    )


def register_row_run(
    run: RowRun,
    *,
    scope_index: ScopeIndexPolicy,
    orchestration: InferenceStreamOrchestration | None = None,
    initialize_ladder: bool = True,
) -> None:
    """Register one RowRun for orchestrator tier_solve wire build and execution.

    ``scope_index`` says whether the run becomes the scope's indexed run, the
    one :func:`claim_tier_ladder` stamps: ``TAKE`` always, ``TAKE_IF_VACANT``
    only when no ``REGISTERED`` run is indexed for the scope. The check and the
    write share one lock hold. A run that does not take the index stays
    registered and is retired at the scope's next claim.
    """
    if initialize_ladder and run.ladder_state is None:
        initialize_tier_ladder_state(run, orchestration=orchestration)
    run.phase = RowRunPhase.REGISTERED
    scope_key = _session_scope_key(run.session)
    with _lock:
        # Same-scope re-register supersedes prior cancelled admission (preempt path).
        _supersede_cancelled_for_scope_locked(scope_key)
        _forget_cancelled_locked(run.run_id)
        _runs_by_id[run.run_id] = run
        if (
            scope_index is ScopeIndexPolicy.TAKE
            or _registered_run_for_scope_key_locked(scope_key) is None
        ):
            _run_id_by_scope_key[scope_key] = run.run_id


def get_row_run(run_id: str) -> RowRun | None:
    """Return a retained REGISTERED or DETACHED shell, if any."""
    with _lock:
        return _runs_by_id.get(run_id)


def get_row_run_for_scope(scope: ComputeScope) -> RowRun | None:
    """Return the ``REGISTERED`` RowRun indexed for ``scope``, if any."""
    with _lock:
        return _registered_run_for_scope_key_locked(_scope_key(scope))


def _registered_run_for_scope_key_locked(scope_key: ScoresScopeKey) -> RowRun | None:
    run_id = _run_id_by_scope_key.get(scope_key)
    if run_id is None:
        return None
    run = _runs_by_id.get(run_id)
    if run is None or run.phase is not RowRunPhase.REGISTERED:
        return None
    return run


def claim_tier_ladder(
    scope: ComputeScope,
    *,
    execution_generation: int,
    scores_epoch: int,
) -> LadderClaim | None:
    """Choose the RowRun whose ladder serves this scores node execution, and stamp it.

    One hold of the registry lock chooses the winner, hands an unfinished
    ladder over to it, retires every other run for the scope and stamps the
    winner, so a run registered concurrently is either seen here or survives
    to win the next claim.

    The winner is the ``REGISTERED`` run indexed for the scope (see
    :class:`ScopeIndexPolicy` for which run that is). With none, it
    is the stamped run (normally ``DETACHED`` after its stream closed) while
    the stamp serves this execution and scores epoch. When the serving stamp
    names another run whose ladder is unfinished, that ladder
    (``ladder_state`` and ``orchestration``) moves to the winner; a stale
    stamp or a finished ladder is not inherited, so the winner keeps its own
    fresh ladder. Every other ``REGISTERED`` or ``DETACHED`` run for the scope
    is retired (the RETIRE side) and named in the claim.

    With no winner, a stale stamp is released (retiring its ``DETACHED``
    shell) and None is returned: the caller admits, which does I/O outside
    this lock, and claims again.

    Hand-over holds only the registry lock and never takes a ``tier_lock``.
    It relies on this invariant: a stamp that serves the current execution
    names a run with no tier step in flight. Within one execution the node
    runs one step at a time and the wire is built between steps; a new
    execution starts only once the node is terminal, and the only mid-step
    abort (``cancel_run``) drops the run. A change that lets a new execution
    start while a step of the old one runs (the #633 game-change abort) must
    recheck it.
    """
    scope_key = _scope_key(scope)
    with _lock:
        stamp = _ladder_stamp_by_scope_key.get(scope_key)
        serving_stamp = (
            stamp
            if stamp is not None
            and stamp.serves(execution_generation=execution_generation, scores_epoch=scores_epoch)
            else None
        )
        winner = _registered_run_for_scope_key_locked(scope_key)
        if winner is None and serving_stamp is not None:
            winner = _runs_by_id[serving_stamp.run_id]
        if winner is None:
            if stamp is not None:
                _release_ladder_stamp_locked(scope_key)
            return None
        handed_over = (
            serving_stamp is not None
            and serving_stamp.run_id != winner.run_id
            and _hand_over_unfinished_ladder_locked(_runs_by_id[serving_stamp.run_id], winner)
        )
        _ladder_stamp_by_scope_key[scope_key] = TierLadderStamp(
            winner.run_id, execution_generation, scores_epoch
        )
        retired_run_ids = tuple(
            run_id
            for run_id, other in _runs_by_id.items()
            if run_id != winner.run_id and _session_scope_key(other.session) == scope_key
        )
        for run_id in retired_run_ids:
            _retire_row_run_locked(run_id)
        return LadderClaim(
            run=winner, retired_run_ids=retired_run_ids, ladder_handed_over=handed_over
        )


def _hand_over_unfinished_ladder_locked(holder: RowRun, winner: RowRun) -> bool:
    """Move ``holder``'s ladder to ``winner`` unless it is finished. Caller holds ``_lock``."""
    ladder_state = holder.ladder_state
    if ladder_state is None or ladder_state.ladder_complete:
        return False
    winner.ladder_state = ladder_state
    winner.orchestration = holder.orchestration
    return True


def release_tier_ladder_for_scope(scope: ComputeScope, *, execution_generation: int) -> None:
    """Release the scope's ladder stamp when its scores node execution ends.

    A stamp written for a later node execution is left alone.
    """
    scope_key = _scope_key(scope)
    with _lock:
        stamp = _ladder_stamp_by_scope_key.get(scope_key)
        if stamp is not None and stamp.execution_generation == execution_generation:
            _release_ladder_stamp_locked(scope_key)


def get_row_run_phase(run_id: str) -> RowRunPhase | None:
    """Retained shell phase only (``REGISTERED`` / ``DETACHED``); never admission."""
    with _lock:
        run = _runs_by_id.get(run_id)
        return None if run is None else run.phase


def get_persist_admission(run_id: str) -> PersistAdmission:
    """Registry-internal admission lookup (shell vs compact cancel vs absent).

    Not a production persist gate. Public callers use
    :func:`decide_scores_row_persist`. This probe exists for admission-memory
    unit tests only.
    """
    with _lock:
        return _persist_admission_locked(run_id)


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Sole production persist gate: atomic admission + phase → ``PersistDecision``.

    Holds ``_lock`` for the whole map so callers never compose
    :func:`get_persist_admission` and :func:`get_row_run_phase` across two
    lock acquisitions. Once returned, a later cancel does not revoke the
    decision for that persist attempt.

    Mapping (via :func:`persist_decision_from_admission`):

    - ``ALLOW`` + ``REGISTERED`` → ``allow(retire_after_write=False)``
    - ``ALLOW`` + ``DETACHED`` → ``allow(retire_after_write=True)``
    - ``CANCEL_DENY`` → ``refuse(should_retire=True)``
    - ``ABSENT`` → ``refuse(should_retire=False)``

    Both refuse outcomes must not write. Persist policy treats them as silent
    no-ops. Cancel intent must go through
    :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`
    (``RowLifecycleOp.CANCEL``); the live cancel token is not a persist gate.
    """
    with _lock:
        admission = _persist_admission_locked(run_id)
        phase = None
        if admission is PersistAdmission.ALLOW:
            run = _runs_by_id.get(run_id)
            phase = None if run is None else run.phase
        return persist_decision_from_admission(admission, phase=phase)


def _persist_admission_locked(run_id: str) -> PersistAdmission:
    """Admission probe. Caller holds ``_lock``."""
    if run_id in _runs_by_id:
        return PersistAdmission.ALLOW
    if run_id in _cancelled_admissions:
        return PersistAdmission.CANCEL_DENY
    return PersistAdmission.ABSENT


def _detach_row_run(run_id: str) -> None:
    """Registry-private DETACH side. Public API: ``apply_scores_row_lifecycle``.

    Transition ``REGISTERED`` → ``DETACHED``; clear scope index; keep by id.
    Detach must not destroy admission state: late persist still finds the shell.
    A tier ladder stamp stays, so the scope's next ``tier_solve`` continuation
    can resume this run. No-op when missing or already cancelled (compact).
    ``DETACHED`` stays ``DETACHED``.
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


def _mark_row_run_cancelled(run_id: str) -> RowRun | None:
    """Registry-private CANCEL admission side. Public API: ``apply_scores_row_lifecycle``.

    Record cancelled admission; drop any shell; return the dropped shell if any.
    Compact cancelled memory is scope-keyed (one outstanding cancel per scores
    scope). The dropped shell is not painted with a cancel phase -- cancel is
    admission memory only. Lifecycle also seals stream cancel and cancels the
    session token.
    """
    with _lock:
        dropped = _drop_shell_locked(run_id)
        if dropped is not None:
            _record_cancelled_locked(run_id, _session_scope_key(dropped.session))
            return dropped
        # Already compact-cancelled (or never registered): leave admission as-is.
        return None


def _retire_row_run(run_id: str) -> None:
    """Registry-private RETIRE side. Public API: ``apply_scores_row_lifecycle``."""
    with _lock:
        _retire_row_run_locked(run_id)


def clear_row_runs() -> None:
    """Drop every retained RowRun and cancelled admission (full invalidate / shutdown)."""
    with _lock:
        _runs_by_id.clear()
        _run_id_by_scope_key.clear()
        _tier_callbacks_by_run_id.clear()
        _cancelled_admissions.clear()
        _cancelled_run_by_scope.clear()
        _ladder_stamp_by_scope_key.clear()


def register_tier_callbacks(run_id: str, callbacks: InferenceTierJobCallbacks) -> None:
    with _lock:
        _tier_callbacks_by_run_id[run_id] = callbacks


def get_tier_callbacks(run_id: str) -> InferenceTierJobCallbacks | None:
    with _lock:
        return _tier_callbacks_by_run_id.get(run_id)


def reset_tier_row_run_registry_for_tests() -> None:
    clear_row_runs()
