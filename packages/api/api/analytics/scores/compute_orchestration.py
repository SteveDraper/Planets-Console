"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

from typing import Any

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
    materialization probe fleet uses). A missing ``RowRun`` while evidence is still
    open must not empty-complete the scores node -- that falsely unlocks fleet with
    ``turnEvidenceAtN=False`` and leaves the scores stream without a rowComplete.

    When ensure has admitted (cheap ephemeral, scheduler attach race, etc.) but no
    registry ``RowRun`` is ready yet, return ``{runId: None}`` so
    ``run_scores_tier_solve`` continues and rebuilds after admit -- not a hard
    ``RuntimeError``. Raise only when ensure still needs work after the admit attempt
    (invariant: schedule/admit should have produced a RowRun).
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
        if ensure_satisfied:
            # Ensure admitted without a registry RowRun (e.g. cheap ephemeral) or a
            # peer is still registering: wait via continue rebuild.
            return {"runId": None}
        raise RuntimeError(
            "scores tier_solve requires a registered RowRun when turn evidence "
            f"is not closed and ensure still needs work "
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
    """Attach an in-progress scheduler RowRun into the tier registry when missing."""
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


def tier_job_outcome_to_step_result(run: RowRun, outcome: TierJobOutcome) -> StepResult:
    """Map one inference tier job outcome to an orchestrator step result.

    Soft / empty terminals must not ``complete`` the scores node while turn
    evidence is still open: that unlocks same-turn fleet ENSURE and triggers the
    fleet ``persist_deferred`` → force_fresh scores reopen loop. Persist only
    statuses that close evidence on disk; otherwise ``continue`` so the wire
    rebuilds (admit, adopt RowRun, or evidence-closed skip).
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
        return StepResult(outcome="continue", payload=payload)

    return StepResult(outcome="continue")


def run_scores_tier_solve(job_wire: dict[str, Any]) -> StepResult:
    """Run one scores inference tier step and return an explicit orchestrator outcome.

    Empty complete is allowed only for the evidence-closed skip sentinel. Open-evidence
    wait wires (``runId: None`` without ``evidenceClosed``) and missing ``RowRun``
    lookups return ``continue`` so the orchestrator rebuilds: evidence closes (skip),
    a RowRun is scheduled/adopted, or wire-build raises only when ensure still needs
    work after admit failed.
    """
    run_id = job_wire.get("runId")
    if run_id is None:
        if job_wire.get("evidenceClosed") is True:
            # Skip sentinel from ``build_scores_tier_solve_job_wire`` when turn
            # evidence is already closed -- no CP-SAT.
            return StepResult(outcome="complete")
        # Open-evidence wait / stale skip without closed marker: rebuild wire.
        return StepResult(outcome="continue")
    if not isinstance(run_id, str):
        raise TypeError("scores tier_solve job wire requires string runId")
    run = get_row_run(run_id)
    if run is None:
        # Cross-binding race: peer may have finalized/unregistered the shared RowRun.
        # Do not empty-complete here -- that unlocked fleet with open scores evidence
        # and left the scoreboard in-progress. Continue so wire-build re-checks
        # ``is_satisfied`` / re-ensures a RowRun.
        return StepResult(outcome="continue")

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


def _persist_orphan_row_complete(
    services: object,
    scope: ComputeScope,
    row_complete: RowComplete,
) -> None:
    """Write a persistable RowComplete when the live RowRun is already gone."""
    from api.analytics.scores.export_precedence import is_durable_turn_evidence_row_status
    from api.serialization.inference_row_persistence import (
        persisted_inference_row_from_wire_complete,
    )
    from api.transport.inference_stream_wire import row_complete_to_complete_wire_event

    export_scope = _export_scope_for_compute(scope)
    if export_scope is None or export_scope.player_id is None:
        return
    persistence = getattr(services, "persistence", None)
    if persistence is None:
        return
    status = row_complete.wire_payload.status
    if not is_durable_turn_evidence_row_status(status):
        return
    wire_event = row_complete_to_complete_wire_event(row_complete)
    persistence.put_row(
        export_scope.game_id,
        export_scope.perspective,
        export_scope.turn,
        export_scope.player_id,
        persisted_inference_row_from_wire_complete(wire_event),
    )


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

        services = resolve_scores_services(ctx)
        if services.persistence is None:
            return

        run = get_row_run(run_id)
        if run is not None:
            if run.session.cancel_token.is_cancelled():
                # Cancelled rows are aborted off ``running`` before persist; no-op is safe.
                return
            services.persistence.persist_row_complete(run.session, row_complete)
            return

        # Peer preempt/finalize may have unregistered the RowRun after the tier
        # produced a persistable outcome. The RowComplete payload is still enough
        # to close turn evidence; writing avoids unlocking fleet with open evidence.
        _persist_orphan_row_complete(services, scope, row_complete)

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
