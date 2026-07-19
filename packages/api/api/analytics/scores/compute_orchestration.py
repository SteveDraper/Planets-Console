"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

from enum import StrEnum
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
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    get_row_run_for_scope,
    get_tier_callbacks,
    register_row_run,
)
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import WILDCARD, ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs, StepResult
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator

SCORES_MATERIALIZE = "materialize"
SCORES_TIER_SOLVE = "tier_solve"
SCORES_TIER_SOLVE_PROFILE_INDEX = 1

SCORES_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))


class ScoresParkReason(StrEnum):
    """Reasons scores tier solving intentionally waits for a later wake."""

    NON_DURABLE_ROW_COMPLETE = "scores_non_durable_row_complete"
    EMPTY_TIER_OUTCOME = "scores_empty_tier_outcome"
    MISSING_ROW_RUN = "scores_missing_row_run"


class ScoresWakeReason(StrEnum):
    """Publishers allowed to resume scores tier solving after a soft park."""

    ROW_RUN_ADOPTED = "scores_row_run_adopted"
    EVIDENCE_CLOSED = "scores_evidence_closed"
    STREAM_RESCHEDULED = "scores_stream_rescheduled"


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
            return {"runId": None, "evidenceClosed": True}
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

    return {"runId": run.run_id}


def _adopt_scheduler_row_run_for_tier_wire(
    ctx: AnalyticQueryContext,
    export_scope: ExportScope,
) -> RowRun | None:
    """Attach an in-progress scheduler RowRun into the tier registry when missing.

    Ensure may report satisfied because the inference scheduler already owns a live
    row while the tier registry was cleared (detach / peer unregister). Adopt must
    succeed in that case so wire build never parks without an armed wake publisher.
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

    Fleet ENSURE-depends on same-turn scores. Completing after materialize alone
    unlocked fleet before inference solutions existed; continuing keeps the scores
    node non-terminal until tier_solve finishes (or skips when no RowRun is needed).

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
    """Submit an encoded scores wake publisher through one coordinator."""
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
    if reason in {
        ScoresWakeReason.ROW_RUN_ADOPTED,
        ScoresWakeReason.EVIDENCE_CLOSED,
    }:
        return resolved_orchestrator.wake_if_parked(request) is not None
    resolved_orchestrator.submit(request)
    return True


def tier_job_outcome_to_step_result(run: RowRun, outcome: TierJobOutcome) -> StepResult:
    """Map one inference tier job outcome to an orchestrator step result.

    Soft / empty terminals must not ``complete`` the scores node while turn
    evidence is still open: that unlocks same-turn fleet ENSURE and triggers the
    fleet ``persist_deferred`` → force_fresh scores reopen loop. Persist only
    statuses that close evidence on disk. Non-durable or empty outcomes park
    (``outcome="park"`` → node ``parked``) until ``force_fresh`` wake -- not hot
    ``continue``.

    Park sites and wake owners:

    - Non-durable ``rowComplete`` → park (+ soft stream delivery on park notify);
      wake via stream reschedule / evidence close / fleet reopen
    - Empty ``TierJobOutcome`` → park (cheap admission soft-stream when available;
      otherwise silent); wake via stream reschedule / RowRun re-adopt
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
        return StepResult(
            outcome="park",
            payload=payload,
            park_reason=ScoresParkReason.NON_DURABLE_ROW_COMPLETE,
        )

    return StepResult(outcome="park", park_reason=ScoresParkReason.EMPTY_TIER_OUTCOME)


def run_scores_tier_solve(job_wire: dict[str, Any]) -> StepResult:
    """Run one scores inference tier step and return an explicit orchestrator outcome.

    Empty complete is allowed only for the evidence-closed skip sentinel. A bare
    ``runId: None`` wire is an invariant break (wire build must attach or
    skip-complete). Missing ``RowRun`` lookups park until a replacement is
    registered (``ROW_RUN_ADOPTED``) or evidence closes.

    Park sites and wake owners (no soft stream terminal -- wait for work):

    - Missing ``RowRun`` → park; wake when a replacement ``RowRun`` is registered
      (``enqueue_tier_ladder``) or evidence closes
    """
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
        # Cross-binding race: peer may have finalized/unregistered the shared RowRun.
        # Do not empty-complete here -- that unlocked fleet with open scores evidence
        # and left the scoreboard in-progress. Park until wire-build can re-check
        # ``is_satisfied`` / re-ensures a RowRun.
        return StepResult(outcome="park", park_reason=ScoresParkReason.MISSING_ROW_RUN)

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

        # Cancel vs detach: cancel intent records a generation-scoped fence before
        # unregister so late persist still skips. Detach records a known-run allow
        # (not FSM OPEN). Unknown run_id with neither RowRun nor allow must not write.
        decision = decide_scores_row_persist(run_id)
        if decision is PersistDecision.DENY_CANCEL:
            return
        if decision is PersistDecision.REFUSE_UNKNOWN:
            raise RuntimeError(
                "scores persist refused: unknown run_id with no RowRun and no "
                f"known-run allow (run_id={run_id!r})"
            )

        services.persistence.persist_row_complete_for_scope(
            row_complete,
            game_id=export_scope.game_id,
            perspective=export_scope.perspective,
            host_turn=export_scope.turn,
            player_id=export_scope.player_id,
        )

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
