"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import FleetTurnSnapshot
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    TierJobOutcome,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    records_for_scope,
    resolution_from_fleet_records,
    resolve_prior_turn_fleet_torp_overlay,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.export_precedence import is_durable_turn_evidence_row_status
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run,
    get_row_run_for_scope,
    get_tier_callbacks,
    register_row_run,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.scores_park_wake import ScoresWakeReason, SoftTerminalReason
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import WILDCARD, ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs, StepResult
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings
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
        ComputeStepSpec(step_kind=SCORES_TIER_SOLVE, backend="thread"),
    ),
)


def _scores_prior_fleet_scope(
    scope: ComputeScope,
    *,
    settings: GameSettings,
) -> ComputeScope | None:
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        return None
    if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
        return None
    if scope.turn <= accelerated_ensure_floor(settings, scope.turn):
        return None
    return ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn - 1,
        player_id=scope.player_id,
    )


def _resolution_from_persisted_fleet_wire(
    persisted_wire: dict[str, object],
    export_scope: ExportScope,
    *,
    prior_turn,
) -> PriorTurnFleetTorpResolution:
    persisted = persisted_fleet_ledger_from_json(persisted_wire)
    snapshot = FleetTurnSnapshot(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        players=[persisted.ledger],
    )
    records = records_for_scope(snapshot, export_scope)
    return resolution_from_fleet_records(records, prior_turn=prior_turn)


def _resolve_prior_fleet_for_tier_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext,
) -> PriorTurnFleetTorpResolution:
    export_scope = _export_scope_for_compute(scope)
    if export_scope is None:
        raise ValueError("scores tier_solve requires concrete scores scope")

    turn = ctx.load_turn(export_scope.turn)
    if turn is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")

    prior_fleet_scope = _scores_prior_fleet_scope(scope, settings=turn.settings)
    if prior_fleet_scope is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    prior_export_scope = compute_scope_to_export_scope(prior_fleet_scope)
    prior_turn = ctx.load_turn(prior_fleet_scope.turn)
    fleet_result_wire = dependency_outputs.get(prior_fleet_scope)
    if isinstance(fleet_result_wire, dict) and prior_turn is not None:
        persisted_wire = fleet_result_wire.get("persistedLedgerWire")
        if isinstance(persisted_wire, dict):
            return _resolution_from_persisted_fleet_wire(
                persisted_wire,
                prior_export_scope,
                prior_turn=prior_turn,
            )

    return resolve_prior_turn_fleet_torp_overlay(
        turn=turn,
        player_id=export_scope.player_id,
        load_turn=ctx.load_turn,
        query_context=ctx,
        ensure=False,
    )


def _apply_fleet_resolution_to_row_run(
    run: RowRun,
    resolution: PriorTurnFleetTorpResolution,
) -> None:
    session = run.session
    session.fleet_torp_overlay = resolution.overlay
    session.fleet_torp_input_status = resolution.input_status
    session.prior_fleet_max_tech_by_axis = resolution.prior_fleet_max_tech_for_admission()
    ladder_state = run.ladder_state
    if ladder_state is not None:
        ladder_state.fleet_torp_overlay = resolution.overlay
        ladder_state.prior_fleet_max_tech_by_axis = session.prior_fleet_max_tech_by_axis


def build_scores_materialize_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Materialize scores export tree on the orchestration plane."""
    from api.analytics.scores.exports import ensure_scores_export, materialize_scores_export_tree

    del dependency_outputs
    if ctx is None:
        raise RuntimeError("scores materialize job wire requires AnalyticQueryContext")
    export_scope = compute_scope_to_export_scope(scope)
    ensure_scores_export(ctx, export_scope)
    tree = materialize_scores_export_tree(ctx, export_scope)
    return {"exportTree": tree}


def build_scores_tier_solve_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Assemble a serializable job wire for one scores inference tier step.

    Skip sentinel (``runId: None``, ``evidenceClosed: True``) is allowed only when
    turn evidence is already closed (persisted / durable terminal under the same
    materialization probe fleet uses).

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
        # Materialize already ensures; re-ensure covers tier_solve entry submits and
        # races where the stream has not registered yet but admit can still schedule.
        from api.analytics.scores.exports import ensure_scores_export

        ensure_satisfied = ensure_scores_export(ctx, export_scope)
        run = get_row_run_for_scope(scope)
    if run is None:
        run = _adopt_scheduler_row_run_for_tier_wire(ctx, export_scope)
    if run is None:
        if ScoresPersistencePolicy().is_satisfied(ctx, scope):
            export_scope = compute_scope_to_export_scope(scope)
            return {
                "runId": None,
                "evidenceClosed": True,
                "gameId": scope.game_id,
                "perspective": scope.perspective,
                "turn": scope.turn,
                "playerId": scope.player_id,
            }
        raise RuntimeError(
            "scores tier_solve invariant broken: ensure "
            f"{'satisfied' if ensure_satisfied else 'unsatisfied'} but no attachable "
            f"RowRun while turn evidence is still open "
            f"(game_id={scope.game_id}, perspective={scope.perspective}, "
            f"turn={scope.turn}, player_id={scope.player_id})"
        )

    fleet_resolution = _resolve_prior_fleet_for_tier_wire(
        scope,
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    _apply_fleet_resolution_to_row_run(run, fleet_resolution)

    return {
        "runId": run.run_id,
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn,
        "playerId": scope.player_id,
    }


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


def run_scores_tier_solve(job_wire: dict[str, Any]) -> StepResult:
    """Run one scores inference tier step and return an explicit orchestrator outcome."""
    run_id = job_wire.get("runId")
    if run_id is None:
        if job_wire.get("evidenceClosed") is True:
            # Skip sentinel from ``build_scores_tier_solve_job_wire`` when turn
            # evidence is already closed -- no CP-SAT.
            return StepResult(outcome="complete")
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
    return {"runId": run.run_id, "rowComplete": row_complete}


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
        run_id = result_wire.get("runId")
        if not isinstance(run_id, str):
            raise TypeError("scores persist result wire missing string runId")
        row_complete = result_wire.get("rowComplete")
        if not isinstance(row_complete, RowComplete):
            raise TypeError("scores persist result wire missing RowComplete payload")

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
        from api.analytics.export_context import export_service_for
        from api.analytics.fleet.compute_services import FleetComputeServices

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None or export_scope.player_id is None:
            return 0
        if export_scope.turn <= 1:
            return 0

        fleet_services = export_service_for(ctx, FLEET_ANALYTIC_ID, FleetComputeServices)
        if fleet_services is None:
            injected = ctx.export_services.get(FLEET_ANALYTIC_ID)
            if isinstance(injected, FleetComputeServices):
                fleet_services = injected
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
