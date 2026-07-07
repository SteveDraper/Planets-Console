"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import FleetTurnSnapshot
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetTorpOverlay,
    launcher_belief_set_from_fleet_records,
)
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    TierJobOutcome,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    resolve_prior_turn_fleet_torp_overlay,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    get_row_run_for_scope,
)
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import WILDCARD, ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs, StepResult

SCORES_MATERIALIZE = "materialize"
SCORES_TIER_SOLVE = "tier_solve"

SCORES_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

SCORES_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(
        ComputeStepSpec(step_kind=SCORES_MATERIALIZE, backend="inline"),
        ComputeStepSpec(step_kind=SCORES_TIER_SOLVE, backend="thread"),
    ),
)

_PERSISTABLE_ROW_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})


def _scores_prior_fleet_scope(scope: ComputeScope) -> ComputeScope | None:
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        return None
    if scope.turn <= 1:
        return None
    if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
        return None
    return ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn - 1,
        player_id=scope.player_id,
    )


def _overlay_from_persisted_fleet_wire(
    persisted_wire: dict[str, object],
    export_scope: ExportScope,
) -> FleetTorpOverlay:
    persisted = persisted_fleet_ledger_from_json(persisted_wire)
    snapshot = FleetTurnSnapshot(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        players=[persisted.ledger],
    )
    records = []
    for ledger in ledgers_for_scope(snapshot, export_scope):
        records.extend(ledger.records)
    belief = launcher_belief_set_from_fleet_records(records)
    return FleetTorpOverlay(belief_set=belief)


def _resolve_prior_fleet_for_tier_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext,
) -> PriorTurnFleetTorpResolution:
    export_scope = _export_scope_for_compute(scope)
    if export_scope is None:
        raise ValueError("scores tier_solve requires concrete scores scope")
    if export_scope.turn <= 1:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    prior_fleet_scope = _scores_prior_fleet_scope(scope)
    if prior_fleet_scope is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    prior_export_scope = compute_scope_to_export_scope(prior_fleet_scope)
    fleet_result_wire = dependency_outputs.get(prior_fleet_scope)
    if isinstance(fleet_result_wire, dict):
        persisted_wire = fleet_result_wire.get("persistedLedgerWire")
        if isinstance(persisted_wire, dict):
            return PriorTurnFleetTorpResolution(
                overlay=_overlay_from_persisted_fleet_wire(persisted_wire, prior_export_scope),
                input_status="applied",
            )

    turn = ctx.load_turn(export_scope.turn)
    if turn is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")

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
    ladder_state = run.ladder_state
    if ladder_state is not None:
        ladder_state.fleet_torp_overlay = resolution.overlay


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
    """Assemble a serializable job wire for one scores inference tier step."""
    if ctx is None:
        raise RuntimeError("scores tier_solve job wire requires AnalyticQueryContext")

    run = get_row_run_for_scope(scope)
    if run is None:
        raise RuntimeError("scores tier_solve requires a registered RowRun for scope")

    fleet_resolution = _resolve_prior_fleet_for_tier_wire(
        scope,
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    _apply_fleet_resolution_to_row_run(run, fleet_resolution)

    return {"runId": run.run_id}


def run_scores_materialize(job_wire: dict[str, Any]) -> StepResult:
    """Inline scores materialize completes without orchestrator-owned persistence."""
    return StepResult(outcome="complete", payload=job_wire["exportTree"])


def tier_job_outcome_to_step_result(run: RowRun, outcome: TierJobOutcome) -> StepResult:
    """Map one inference tier job outcome to an orchestrator step result."""
    if outcome.enqueue_continuation:
        if outcome.next_ladder_state is not None:
            run.ladder_state = outcome.next_ladder_state
        return StepResult(outcome="continue")

    if outcome.row_complete is not None:
        payload = _tier_persist_payload(run, outcome.row_complete)
        status = outcome.row_complete.wire_payload.status
        if status in _PERSISTABLE_ROW_STATUSES:
            return StepResult(outcome="persist", payload=payload)
        return StepResult(outcome="complete", payload=payload)

    return StepResult(outcome="complete")


def run_scores_tier_solve(job_wire: dict[str, Any]) -> StepResult:
    """Run one scores inference tier step and return an explicit orchestrator outcome."""
    run_id = job_wire.get("runId")
    if not isinstance(run_id, str):
        raise TypeError("scores tier_solve job wire requires string runId")
    run = get_row_run(run_id)
    if run is None:
        raise RuntimeError(f"scores tier_solve missing registered RowRun for runId {run_id!r}")

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
        from api.analytics.scores.exports import is_scores_export_ensure_satisfied

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return False
        return is_scores_export_ensure_satisfied(ctx, export_scope)

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> None:
        del scope
        if not isinstance(result_wire, dict):
            raise TypeError(
                f"scores persist result wire must be dict, got {type(result_wire).__name__}"
            )
        run_id = result_wire.get("runId")
        if not isinstance(run_id, str):
            raise TypeError("scores persist result wire missing string runId")
        run = get_row_run(run_id)
        if run is None:
            raise RuntimeError(f"scores persist missing registered RowRun for runId {run_id!r}")
        row_complete = result_wire.get("rowComplete")
        if not isinstance(row_complete, RowComplete):
            raise TypeError("scores persist result wire missing RowComplete payload")

        services = resolve_scores_services(ctx)
        if services.persistence is None:
            return
        services.persistence.persist_row_complete(run.session, row_complete)

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

        return fleet_services.persistence.invalidation_generation(
            scope.game_id,
            scope.perspective,
            export_scope.player_id,
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
