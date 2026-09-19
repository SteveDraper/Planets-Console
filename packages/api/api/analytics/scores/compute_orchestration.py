"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    TierJobOutcome,
    outcome_after_ladder_complete,
    run_inference_tier_job,
    solve_context,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.compute_plane.tier_solve_leaf import process_safe_ladder_state
from api.analytics.scores.export_precedence import is_durable_turn_evidence_row_status
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.prior_fleet_resolution import (
    fleet_compute_services,
    resolve_prior_fleet_for_scores,
)
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run,
    get_row_run_for_scope,
    get_tier_callbacks,
    register_row_run,
)
from api.analytics.scores.tier_solve_backend import (
    SCORES_TIER_SOLVE_BACKEND_PROCESS,
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
from api.analytics.scores_defer_wake import ScoresWakeReason, SoftTerminalReason
from api.compute.profile import AnalyticComputeProfile, ComputeBackend, ComputeStepSpec
from api.compute.scope import ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import (
    DependencyOutputs,
    StepResult,
    orchestration_plane_skip_result,
)
from api.config import get_config
from api.streaming.table_stream.row_run_admission import RowLifecycleOp

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator

SCORES_MATERIALIZE = "materialize"
SCORES_TIER_SOLVE = "tier_solve"
SCORES_TIER_SOLVE_PROFILE_INDEX = 1

SCORES_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

SCORES_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(
        ComputeStepSpec(step_kind=SCORES_MATERIALIZE, backend="inline"),
        ComputeStepSpec(
            step_kind=SCORES_TIER_SOLVE,
            backend="thread",
            gil_overlap="native_release",
        ),
    ),
    # REST table is a TurnInfo projection. Inference ensure/stream is a
    # different caller; routing table GET through ensure would wait on
    # fleet@(N-1) and turn scores into a gap-fill barrier.
    route_table_map=False,
)


def resolve_scores_step_backend(step_kind: str, declared: ComputeBackend) -> ComputeBackend:
    """Return the effective backend for one scores compute step.

    ``tier_solve`` follows occupancy / freeze policy via
    ``resolve_scores_tier_solve_backend``. Other steps keep ``declared``.
    Sampled at dispatch/flush, not at import.
    """
    if step_kind != SCORES_TIER_SOLVE:
        return declared
    return resolve_scores_tier_solve_backend()


def _apply_fleet_resolution_to_row_run(
    run: RowRun,
    resolution: PriorTurnFleetTorpResolution,
) -> None:
    session = run.session
    session.fleet_torp_overlay = resolution.overlay
    session.fleet_torp_input_status = resolution.input_status
    session.prior_fleet_max_tech_by_axis = resolution.prior_fleet_max_tech_for_admission()
    session.prior_fleet_records = resolution.records
    ladder_state = run.ladder_state
    if ladder_state is not None:
        ladder_state.fleet_torp_overlay = resolution.overlay
        ladder_state.prior_fleet_max_tech_by_axis = session.prior_fleet_max_tech_by_axis
        ladder_state.prior_fleet_records = resolution.records


def build_scores_materialize_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Materialize scores export tree on the orchestration plane."""
    from api.analytics.scores.exports import (
        admit_scores_export_work,
        materialize_scores_export_tree,
    )

    del dependency_outputs
    if ctx is None:
        raise RuntimeError("scores materialize job wire requires AnalyticQueryContext")
    export_scope = compute_scope_to_export_scope(scope)
    # Admit only -- never ensure_scope / wait. Fleet deps are already terminal on the DAG.
    admit_scores_export_work(ctx, export_scope, overlay_ensure=False)
    tree = materialize_scores_export_tree(ctx, export_scope)
    return {"exportTree": tree}


def build_scores_tier_solve_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    node_result_wire: object | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Assemble a serializable job wire for one scores inference tier step.

    Orchestration plane: skip sentinel (``runId: None``, ``evidenceClosed: True``,
    ``orchestrationSkip: True``) is allowed only when turn evidence is already
    closed. Open-evidence wires attach a live ``RowRun`` here. Effective backend
    (``resolve_scores_tier_solve_backend``, sampled at this build) selects the
    payload: ``thread`` emits the tiny identity wire (``runId`` + scope ids);
    ``process`` emits the storage-rebuild snapshot so a process-pool leaf can
    rebuild ``InferenceProblem`` without looking up the parent registry.

    Invariant: when ensure is satisfied and evidence is still open, this dispatch
    must attach a ``runId`` (tier registry or successful scheduler adopt). Parking
    on ``{runId: None}`` with open evidence is forbidden -- that state has no armed
    wake publisher and hung dependents (Birds hang). Raise instead.
    """
    if ctx is None:
        raise RuntimeError("scores tier_solve job wire requires AnalyticQueryContext")

    export_scope = _export_scope_for_compute(scope)
    if export_scope is None:
        raise ValueError("scores tier_solve requires concrete scores scope")

    run = get_row_run_for_scope(scope)
    ensure_satisfied = True
    if run is None:
        # Materialize already admits; re-admit covers tier_solve entry submits and
        # races where the stream has not registered yet but admit can still schedule.
        from api.analytics.scores.exports import admit_scores_export_work

        ensure_satisfied = admit_scores_export_work(
            ctx,
            export_scope,
            overlay_ensure=False,
        )
        run = get_row_run_for_scope(scope)
    if run is None:
        run = _adopt_scheduler_row_run_for_tier_wire(ctx, export_scope)
    if run is None:
        if ScoresPersistencePolicy().is_satisfied(ctx, scope):
            export_scope = compute_scope_to_export_scope(scope)
            return {
                WIRE_RUN_ID: None,
                WIRE_EVIDENCE_CLOSED: True,
                WIRE_ORCHESTRATION_SKIP: True,
                WIRE_GAME_ID: scope.game_id,
                WIRE_PERSPECTIVE: scope.perspective,
                WIRE_TURN: scope.turn,
                WIRE_PLAYER_ID: scope.player_id,
            }
        raise RuntimeError(
            "scores tier_solve invariant broken: ensure "
            f"{'satisfied' if ensure_satisfied else 'unsatisfied'} but no attachable "
            f"RowRun while turn evidence is still open "
            f"(game_id={scope.game_id}, perspective={scope.perspective}, "
            f"turn={scope.turn}, player_id={scope.player_id})"
        )

    turn = ctx.load_turn(export_scope.turn)
    if turn is None or export_scope.player_id is None:
        fleet_resolution = PriorTurnFleetTorpResolution(
            overlay=None,
            input_status="pending",
        )
    else:
        fleet_resolution = resolve_prior_fleet_for_scores(
            ctx,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn_number=export_scope.turn,
            player_id=export_scope.player_id,
            turn=turn,
            dependency_outputs=dependency_outputs,
            overlay_ensure=False,
        )
    # Apply the previous leaf snapshot before this dispatch's fleet overlay so
    # the continued ladder holds current overlay (thread looks up RowRun; process
    # copies it onto the storage-rebuild snapshot).
    apply_scores_tier_solve_step_result(run, node_result_wire)
    _apply_fleet_resolution_to_row_run(run, fleet_resolution)
    if resolve_scores_tier_solve_backend() == SCORES_TIER_SOLVE_BACKEND_PROCESS:
        return _process_safe_tier_solve_job_wire(scope, run)
    return _thread_tier_solve_job_wire(scope, run)


def _adopt_scheduler_row_run_for_tier_wire(
    ctx: AnalyticQueryContext,
    export_scope: ExportScope,
) -> RowRun | None:
    """Re-index a live ``REGISTERED`` RowRun when scope lookup raced ensure.

    ``row_run_for_player`` reads the single registry owner (REGISTERED only).
    ``DETACHED`` shells and cancelled admissions are not adoptable.
    ``register_row_run`` refreshes the scope index if ensure scheduled the row
    before the first ``get_row_run_for_scope`` check.
    """
    if export_scope.player_id is None:
        return None
    from api.analytics.scores.export_snapshot import scores_inference_stream_scope

    services = resolve_scores_services(ctx)
    scheduler_run = services.scheduler.row_run_for_player(
        scores_inference_stream_scope(export_scope),
        export_scope.player_id,
    )
    if scheduler_run is None:
        return None
    register_row_run(
        scheduler_run,
        initialize_ladder=scheduler_run.ladder_state is None,
    )
    return scheduler_run


def apply_scores_tier_solve_step_result(run: RowRun, result: StepResult | object) -> None:
    """Advance parent ``RowRun`` ladder state from a process-plane leaf result.

    The child never holds ``RowRun``. Continue and persist payloads carry a
    catalog-free ``PolicyLadderState`` snapshot that replaces the parent's
    ladder progress. Accepts a ``StepResult`` or the payload dict already
    stored on ``node.result_wire``.
    """
    payload = result.payload if isinstance(result, StepResult) else result
    if not isinstance(payload, dict):
        return
    snapshot = payload.get(WIRE_LADDER_STATE)
    if isinstance(snapshot, PolicyLadderState):
        run.ladder_state = snapshot


def _thread_tier_solve_job_wire(scope: ComputeScope, run: RowRun) -> dict[str, Any]:
    """Tiny identity wire: ``runId`` + scope ids. No storage-rebuild copies."""
    return {
        WIRE_RUN_ID: run.run_id,
        WIRE_GAME_ID: scope.game_id,
        WIRE_PERSPECTIVE: scope.perspective,
        WIRE_TURN: scope.turn,
        WIRE_PLAYER_ID: scope.player_id,
    }


def _process_safe_tier_solve_job_wire(scope: ComputeScope, run: RowRun) -> dict[str, Any]:
    """Process-backend snapshot: scope + storage root + catalog-free ladder."""
    from api.analytics.military_score_inference.inference_row_runner import (
        stream_tier_time_limit_seconds,
    )

    observation, _turn = solve_context(run)
    ladder = run.ladder_state
    return {
        **_thread_tier_solve_job_wire(scope, run),
        WIRE_STORAGE_ROOT: str(Path(get_config().storage_root).resolve()),
        WIRE_LADDER_STATE: None if ladder is None else process_safe_ladder_state(ladder),
        WIRE_OBSERVATION: observation,
        WIRE_TIME_LIMIT_SECONDS: stream_tier_time_limit_seconds(),
    }


def run_scores_materialize(job_wire: dict[str, Any]) -> StepResult:
    """Inline scores materialize then continue into ``tier_solve`` on the same node.

    Fleet finalization PersistDeferred-depends on same-turn scores evidence.
    Completing after materialize alone unlocked finalization before inference
    solutions existed; continuing keeps the scores node non-terminal until
    tier_solve finishes (or skips when no RowRun is needed).

    The export tree is carried as the continue payload so no-work skip paths still
    leave a dependency ``result_wire`` for fleet dispatch.
    """
    export_tree = job_wire["exportTree"]
    return StepResult(outcome="continue", payload=export_tree)


def wake_scores_scope(
    scope: ComputeScope,
    *,
    ctx: AnalyticQueryContext,
    reason: ScoresWakeReason,
    priority_band: str = "background",
    orchestrator: ComputeOrchestrator | None = None,
) -> bool:
    """Submit an encoded scores wake publisher through one coordinator.

    All wake reasons use ``force_fresh`` submit so ``waiting_deps`` nodes refresh
    readiness without the retired soft-park path.
    """
    from api.compute.orchestrator import ComputeRequest
    from api.compute.runtime import get_compute_orchestrator

    resolved_orchestrator = orchestrator or get_compute_orchestrator()
    request = ComputeRequest(
        scope=scope,
        step_kind=SCORES_TIER_SOLVE,
        force_fresh=True,
        ctx=ctx,
        priority_band=priority_band,
    )
    if reason is ScoresWakeReason.STREAM_RESCHEDULED:
        resolved_orchestrator.submit(request)
        return True
    node = resolved_orchestrator.nodes.get(scope)
    if node is None or node.is_terminal or node.state == "running":
        return False
    resolved_orchestrator.submit(request)
    return True


def _scores_compute_scope_for_run(run: RowRun) -> ComputeScope:
    session = run.session
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )


def _waiting_deps_without_submit() -> StepResult:
    """Soft-defer demotion: ``waiting_deps`` with no dependency graft or force_fresh.

    Omits ``wait_recovery`` so the orchestrator demotes without treating this scope
    as its own ENSURE dependency (self-graft leaves ``_deps_complete`` false forever).
    """
    return StepResult(outcome="waiting_deps")


def _emit_soft_defer_and_wait(
    run: RowRun,
    *,
    soft_reason: SoftTerminalReason,
    row_complete: RowComplete | None = None,
    payload: dict[str, object] | None = None,
) -> StepResult:
    from api.analytics.military_score_inference.inference_scheduler import (
        inference_row_scheduler_if_initialized,
    )

    scope = _scores_compute_scope_for_run(run)
    scheduler = inference_row_scheduler_if_initialized()
    if scheduler is not None:
        scheduler.deliver_scores_row_defer_terminal(
            scope,
            soft_reason=soft_reason,
            event=row_complete,
        )
    result = _waiting_deps_without_submit()
    if payload is not None:
        return StepResult(outcome=result.outcome, payload=payload)
    return result


def tier_job_outcome_to_step_result(run: RowRun, outcome: TierJobOutcome) -> StepResult:
    """Map one inference tier job outcome to an orchestrator step result.

    Non-durable or empty outcomes demote the node to ``waiting_deps`` and emit
    soft stream rows from the row path (not orchestrator park). Durable terminals
    persist and complete the scores node.
    """
    if outcome.enqueue_continuation:
        if outcome.next_ladder_state is not None:
            run.ladder_state = outcome.next_ladder_state
        return StepResult(outcome="continue")

    if outcome.row_complete is not None:
        payload = _tier_persist_payload(run, outcome.row_complete)
        status = outcome.row_complete.wire_payload.status
        if is_durable_turn_evidence_row_status(status):
            return StepResult(outcome="persist", payload=payload)
        return _emit_soft_defer_and_wait(
            run,
            soft_reason=SoftTerminalReason.NON_DURABLE_ROW_COMPLETE,
            row_complete=outcome.row_complete,
            payload=payload,
        )

    return _emit_soft_defer_and_wait(
        run,
        soft_reason=SoftTerminalReason.EMPTY_TIER_OUTCOME,
    )


def map_scores_tier_solve_remote_result(scope: ComputeScope, raw: object) -> StepResult:
    """Map a process-plane leaf snapshot onto the parent ``RowRun`` and ``StepResult``.

    Runs on the parent after unpickle, before ``coerce_step_result``. Soft-defer
    and fleet-torp diagnostics come from the live ``RowRun``. SAT is not re-run.
    """
    del scope
    if isinstance(raw, StepResult):
        return raw
    payload = raw if isinstance(raw, dict) else {}
    run_id = payload.get(WIRE_RUN_ID)
    if not isinstance(run_id, str):
        return _waiting_deps_without_submit()
    run = get_row_run(run_id)
    if run is None:
        return _waiting_deps_without_submit()

    with run.tier_lock:
        snapshot = payload.get(WIRE_LADDER_STATE)
        if not isinstance(snapshot, PolicyLadderState):
            outcome: TierJobOutcome | None = TierJobOutcome()
        else:
            apply_scores_tier_solve_step_result(run, payload)
            state = run.ladder_state
            if state is None:
                outcome = TierJobOutcome()
            elif not state.ladder_complete:
                outcome = None
            else:
                observation, turn = solve_context(run)
                outcome = outcome_after_ladder_complete(run, state, observation, turn)
                if outcome.next_ladder_state is not None:
                    run.ladder_state = outcome.next_ladder_state
    if outcome is None:
        return StepResult(outcome="continue", payload=payload)
    return tier_job_outcome_to_step_result(run, outcome)


def run_scores_tier_solve(job_wire: dict[str, Any]) -> StepResult:
    """Run one in-process scores inference tier against the parent ``RowRun``.

    Thread-backend workers share the parent registry. Skip sentinels complete
    via ``orchestration_plane_skip_result`` (same predicate as process dispatch).
    Process-backend workers use ``run_scores_tier_solve_leaf`` instead: that leaf
    rebuilds the problem from ``storageRoot`` and never calls ``get_row_run``.
    The parent maps the leaf snapshot through ``map_scores_tier_solve_remote_result``.
    """
    skip_result = orchestration_plane_skip_result(job_wire)
    if skip_result is not None:
        return skip_result
    run_id = job_wire.get(WIRE_RUN_ID)
    if run_id is None:
        raise RuntimeError(
            "scores tier_solve received open-evidence wait wire without runId; "
            "wire build must attach a RowRun or emit evidenceClosed skip"
        )
    if not isinstance(run_id, str):
        raise TypeError("scores tier_solve job wire requires string runId")
    run = get_row_run(run_id)
    if run is None:
        # Missing RowRun: soft-wait for force_fresh wake to rebuild wire / reschedule.
        # Do not self-graft via PersistDependencyRecovery -- that blocks readiness.
        return _waiting_deps_without_submit()

    callbacks = get_tier_callbacks(run_id)
    if callbacks is None:
        callbacks = InferenceTierJobCallbacks(
            emit_tier_started_progress=lambda: None,
            emit_progress=lambda: None,
            emit_held_solutions=lambda _observation: None,
        )
    outcome = run_inference_tier_job(run, callbacks)
    return tier_job_outcome_to_step_result(run, outcome)


def _tier_persist_payload(run: RowRun, row_complete: RowComplete) -> dict[str, object]:
    return {WIRE_RUN_ID: run.run_id, "rowComplete": row_complete}


class ScoresPersistencePolicy:
    """Orchestrator persistence hooks for per-player scores inference scopes."""

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        """True when scores@N has terminal evidence (not merely a scheduled RowRun)."""
        from api.analytics.scores.exports import is_scores_export_turn_evidence_closed

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return False
        return is_scores_export_turn_evidence_closed(ctx, export_scope)

    def satisfied_result_wire(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
    ) -> None:
        """Scores short-circuit has no cheap rowComplete wire; stream uses admission."""
        del ctx, scope
        return None

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> None:
        if not isinstance(result_wire, dict):
            raise TypeError(
                f"scores persist result wire must be dict, got {type(result_wire).__name__}"
            )
        run_id = result_wire.get(WIRE_RUN_ID)
        if not isinstance(run_id, str):
            raise TypeError("scores persist result wire missing string runId")
        row_complete = result_wire.get("rowComplete")
        if not isinstance(row_complete, RowComplete):
            raise TypeError("scores persist result wire missing RowComplete payload")

        attached = get_row_run(run_id)
        if attached is not None:
            apply_scores_tier_solve_step_result(attached, result_wire)

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None or export_scope.player_id is None:
            return

        services = resolve_scores_services(ctx)
        if services.persistence is None:
            return

        # Cancel vs detach / late-persist retire: sole plan is PersistDecision
        # (atomic registry snapshot). Once taken, a later cancel does not
        # revoke this attempt. Unknown run_id with no admission must not write.
        # Live REGISTERED shells stay until stream finalize retires them so
        # peer bindings can still resolve the same RowRun; DETACHED late
        # persist sets retire_after_write; cancel deny sets should_retire.
        decision = decide_scores_row_persist(run_id)
        if not decision.allowed:
            # Silent no-write for both cancel deny and unknown/absent. Retire
            # only when the refuse carries should_retire (cancel admission).
            if decision.should_retire:
                apply_scores_row_lifecycle(RowLifecycleOp.RETIRE, run_id)
            return

        services.persistence.persist_row_complete_for_scope(
            row_complete,
            game_id=export_scope.game_id,
            perspective=export_scope.perspective,
            host_turn=export_scope.turn,
            player_id=export_scope.player_id,
            fleet_torp_input_status=_fleet_torp_input_status_for_persist(run_id),
        )
        if decision.retire_after_write:
            apply_scores_row_lifecycle(RowLifecycleOp.RETIRE, run_id)

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return
        services = resolve_scores_services(ctx)
        if services.persistence is None or export_scope.player_id is None:
            return
        services.persistence.delete_row(
            export_scope.game_id,
            export_scope.perspective,
            export_scope.turn,
            export_scope.player_id,
        )

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        """Return prior-fleet turn epoch for this scores scope.

        ``scores@N`` tracks ``fleet@(N-1)``'s turn-scoped generation only. Same-player
        activity on other turns must not discard in-flight tier work.
        """
        export_scope = _export_scope_for_compute(scope)
        if export_scope is None or export_scope.player_id is None:
            return 0
        if export_scope.turn <= 1:
            return 0

        fleet_services = fleet_compute_services(ctx)
        if fleet_services is None:
            return 0

        return fleet_services.persistence.turn_invalidation_generation(
            scope.game_id,
            scope.perspective,
            export_scope.player_id,
            export_scope.turn - 1,
        )


def _fleet_torp_input_status_for_persist(run_id: str) -> str | None:
    run = get_row_run(run_id)
    if run is None:
        return None
    return run.session.fleet_torp_input_status


def _export_scope_for_compute(scope: ComputeScope) -> ExportScope | None:
    if scope.player_id == "*" or not isinstance(scope.player_id, int):
        return None
    if scope.turn == "*" or not isinstance(scope.turn, int):
        return None
    if scope.perspective == "*" or not isinstance(scope.perspective, int):
        return None
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )


SCORES_PERSISTENCE_POLICY = ScoresPersistencePolicy()
