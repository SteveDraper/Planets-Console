"""Scores analytic compute orchestrator registration surface."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any, assert_never

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.export_types import ExportScope
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.analytics.military_score_inference.durable_turn_evidence import (
    is_durable_turn_evidence_row_status,
)
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    TierJobContinue,
    TierJobOutcome,
    TierJobRowComplete,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.off_mode_wire import (
    ON_WALK_WIRE_FIELD,
    copy_submission_open_fields,
    parse_off_mode_wire,
)
from api.analytics.scores.export_services import ScoresExportContext, resolve_scores_services
from api.analytics.scores.exports import stored_closed_horwasp_skip
from api.analytics.scores.prior_fleet_resolution import resolve_prior_fleet_for_scores
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    claim_tier_ladder,
    decide_scores_row_persist,
    get_row_run,
    get_tier_callbacks,
)
from api.analytics.scores_assets import ANALYTIC_ID
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import DependencyOutputs, StepResult
from api.exceptions import ScoresTierOutcomeError, ValidationError
from api.streaming.table_stream.row_run_admission import RowLifecycleOp

SCORES_MATERIALIZE = "materialize"
SCORES_TIER_SOLVE = "tier_solve"
SCORES_TIER_SOLVE_PROFILE_INDEX = 1

logger = logging.getLogger(__name__)

SCORES_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

SCORES_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(
        ComputeStepSpec(step_kind=SCORES_MATERIALIZE, backend="inline"),
        ComputeStepSpec(
            step_kind=SCORES_TIER_SOLVE,
            backend="thread",
        ),
    ),
    # REST table is a TurnInfo projection. Inference ensure/stream is a
    # different caller; routing table GET through ensure would wait on
    # fleet@(N-1) and turn scores into a gap-fill barrier.
    route_table_map=False,
)


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
    ladder_state.fleet_torp_overlay = resolution.overlay
    ladder_state.prior_fleet_max_tech_by_axis = session.prior_fleet_max_tech_by_axis
    ladder_state.prior_fleet_records = resolution.records


def build_scores_materialize_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext,
    submission_open: SubmissionOpen,
    **_kwargs: object,
) -> dict[str, Any]:
    """Materialize scores export tree on the orchestration plane."""
    from api.analytics.scores.exports import (
        admit_scores_export_work,
        materialize_scores_export_tree,
    )

    del dependency_outputs
    export_scope = compute_scope_to_export_scope(scope)
    # Admit only -- never ensure_scope / wait. Fleet deps are already terminal on the DAG.
    admit_scores_export_work(
        ctx,
        export_scope,
        overlay_ensure=False,
        backfill_earlier_turns=submission_open.backfill_earlier_turns,
    )
    tree = materialize_scores_export_tree(ctx, export_scope)
    return {"exportTree": tree}


def build_scores_tier_solve_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext,
    submission_open: SubmissionOpen,
    execution_generation: int,
    is_execution_live: Callable[[], bool],
    **_kwargs: object,
) -> dict[str, Any]:
    """Assemble a serializable job wire for one scores inference tier step.

    Horwasp production is not modeled. That classification writes the skip row
    and returns the evidence-closed sentinel before the ladder claim, fleet
    resolution, or the satisfaction probe. The persisted row is the mark
    fleet's materialization probe reads.

    Other skip sentinels (``runId: None``, ``evidenceClosed: True``) are allowed
    only when turn evidence is already closed (persisted / durable terminal under
    the same materialization probe fleet uses). Admission skips (full alliance,
    viewpoint owner, dead, no prior turn) close that evidence because admit
    rewrites the skip row when it is missing; they do not need a ``RowRun``.

    Invariant: when ensure is satisfied and evidence is still open, this dispatch
    must attach a ``runId`` from the tier registry. Parking on ``{runId: None}``
    with open evidence is forbidden -- that state has no armed wake publisher and
    hung dependents (Birds hang). Raise instead.

    The RowRun comes from ``claim_tier_ladder``, one registry operation that
    chooses the run, stamps it with this node execution and the scores epoch,
    hands it an unfinished ladder another run for the scope held, and retires
    every other run for the scope. A continuation whose stream closed
    mid-ladder resumes its own ``DETACHED`` run. With no run to claim, the
    admit runs outside the registry lock and the ladder is claimed again.
    After the claim, the scheduler forgets the retired runs and, on a
    hand-over, the claimed run's stream gets the moved ladder's held solutions
    without an inference evidence announcement. The fleet resolution is
    applied after the claim, so it lands on the ladder the step runs.

    A claim for an execution that ended while its wire was being built raises
    ``ComputeExecutionEndedError`` and changes nothing; the orchestrator
    ignores the failed build of an ended execution.

    The wire carries ``onWalk`` from the node's submission open, so the persist
    it produces classifies stamp versus bump by this execution's walk
    membership.
    """
    export_scope = _export_scope_for_compute(scope)
    if export_scope is None:
        raise ValueError("scores tier_solve requires concrete scores scope")

    horwasp_skip = _horwasp_evidence_closed_skip_wire(ctx, scope, export_scope)
    if horwasp_skip is not None:
        return horwasp_skip

    backfill_earlier_turns = submission_open.backfill_earlier_turns
    scores_epoch = SCORES_PERSISTENCE_POLICY.invalidation_generation(ctx, scope)
    claim_ladder = partial(
        claim_tier_ladder,
        scope,
        execution_generation=execution_generation,
        scores_epoch=scores_epoch,
        is_execution_live=is_execution_live,
    )
    claim = claim_ladder()
    ensure_satisfied = True
    if claim is None:
        # Materialize already admits; re-admit covers tier_solve entry submits and
        # races where the stream has not registered yet but admit can still schedule.
        from api.analytics.scores.exports import admit_scores_export_work

        ensure_satisfied = admit_scores_export_work(
            ctx,
            export_scope,
            overlay_ensure=False,
            backfill_earlier_turns=backfill_earlier_turns,
        )
        claim = claim_ladder()
    if claim is None:
        if ScoresPersistencePolicy().is_satisfied(ctx, scope):
            return _evidence_closed_skip_wire(scope)
        raise RuntimeError(
            "scores tier_solve invariant broken: ensure "
            f"{'satisfied' if ensure_satisfied else 'unsatisfied'} but no attachable "
            f"RowRun while turn evidence is still open "
            f"(game_id={scope.game_id}, perspective={scope.perspective}, "
            f"turn={scope.turn}, player_id={scope.player_id})"
        )
    run = claim.run
    scheduler = resolve_scores_services(ctx).scheduler
    scheduler.forget_runs(claim.retired_run_ids)
    if claim.ladder_handed_over:
        scheduler.deliver_held_solutions_to_stream(run.session)

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
            backfill_earlier_turns=backfill_earlier_turns,
        )
    _apply_fleet_resolution_to_row_run(run, fleet_resolution)

    return {
        "runId": run.run_id,
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn,
        "playerId": scope.player_id,
        ON_WALK_WIRE_FIELD: submission_open.on_walk,
    }


def _evidence_closed_skip_wire(scope: ComputeScope) -> dict[str, Any]:
    """Tier wire that completes with no CP-SAT once turn evidence is closed."""
    return {
        "runId": None,
        "evidenceClosed": True,
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn,
        "playerId": scope.player_id,
    }


def _horwasp_evidence_closed_skip_wire(
    ctx: AnalyticQueryContext,
    scope: ComputeScope,
    export_scope: ExportScope,
) -> dict[str, Any] | None:
    """Return the skip wire once a Horwasp row is stored, before any solve work.

    Fleet finalization reads the persisted inference row and ignores the
    in-memory admission. The stored-row rule is ``closed_horwasp_skip_row``.
    """
    if stored_closed_horwasp_skip(ctx, export_scope) is None:
        return None
    return _evidence_closed_skip_wire(scope)


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


def tier_job_outcome_to_step_result(
    run: RowRun,
    outcome: TierJobOutcome,
    job_wire: Mapping[str, Any],
) -> StepResult:
    """Map one inference tier job outcome to an orchestrator step result.

    A continuation re-queues ``tier_solve``; the runner has already advanced the
    ladder. A terminal persists and completes the scores node. A terminal whose
    status does not close turn evidence breaks the tier job contract and raises
    :class:`ScoresTierOutcomeError`, which fails the node. A row payload copies
    the submission open fields ``job_wire`` carries.
    """
    match outcome:
        case TierJobContinue():
            return StepResult(outcome="continue")
        case TierJobRowComplete(row_complete=row_complete):
            status = row_complete.wire_payload.status
            if not is_durable_turn_evidence_row_status(status):
                raise ScoresTierOutcomeError(run_id=run.run_id, status=status)
            return StepResult(
                outcome="persist",
                payload=_tier_persist_payload(run, row_complete, job_wire),
            )
    assert_never(outcome)


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
        # The claimed run was retired between wire build and this step (a peer
        # claim, a cancel before its abort, a scheduler clear). Continuing runs
        # wire build again, which re-claims, admits, skips on closed evidence or
        # raises, so the node moves on without anything having to wake it.
        logger.info("scores tier_solve missing_row_run %s: continuing to rebuild the wire", run_id)
        return StepResult(outcome="continue")

    callbacks = get_tier_callbacks(run_id)
    if callbacks is None:
        callbacks = InferenceTierJobCallbacks(
            emit_tier_started_progress=lambda: None,
            emit_progress=lambda: None,
            emit_held_solutions=lambda: None,
        )
    outcome = run_inference_tier_job(run, callbacks)
    return tier_job_outcome_to_step_result(run, outcome, job_wire)


def _tier_persist_payload(
    run: RowRun,
    row_complete: RowComplete,
    job_wire: Mapping[str, Any],
) -> dict[str, object]:
    payload: dict[str, object] = {"runId": run.run_id, "rowComplete": row_complete}
    copy_submission_open_fields(job_wire, payload)
    return payload


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
        # Walk membership of the producing execution, carried from its job wire.
        on_walk = parse_off_mode_wire(result_wire).on_walk
        if on_walk is None:
            raise ValidationError(
                f"scores persist result wire requires boolean {ON_WALK_WIRE_FIELD}"
            )

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
            query_context=ctx,
            on_walk=on_walk,
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
        """Return the scores epoch: the fleet term plus the player's hull mask revision."""
        return scores_epoch(fleet_term(ctx, scope), _hull_mask_revision(ctx, scope))


def scores_epoch(fleet_term: int, mask_revision: int) -> int:
    """Combine the scores epoch's two terms.

    Both terms only increase, so their sum moves whenever either moves and
    never returns to an earlier value. Callers compare epochs for equality only.
    """
    return fleet_term + mask_revision


def fleet_term(ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
    """The scores epoch's fleet term: ``fleet@(N-1)``'s turn-scoped generation.

    ``scores@N`` tracks that one prior turn, so same-player fleet activity on
    other turns does not discard in-flight tier work. It is 0 for a scope with
    no prior turn (turn 1 is an admission skip) or no fleet services.
    """
    export_scope = _export_scope_for_compute(scope)
    if export_scope is None or export_scope.player_id is None:
        return 0
    if export_scope.turn <= 1:
        return 0

    fleet_services = lookup_fleet_compute_services(ctx)
    if fleet_services is None:
        return 0

    return fleet_services.persistence.turn_invalidation_generation(
        scope.game_id,
        scope.perspective,
        export_scope.player_id,
        export_scope.turn - 1,
    )


def _hull_mask_revision(ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
    """The scores epoch's mask term: the player's hull mask revision.

    A mask override applies at every turn and perspective, so this term has
    no early return for the turn. It reads no storage and takes no lock: the
    orchestrator reads epochs under its own lock. A context with no scores
    bundle has no mask store and contributes 0.
    """
    if scope.player_id is None:
        return 0
    services = export_service_for(ctx, ANALYTIC_ID, ScoresExportContext)
    if services is None:
        return 0
    return services.mask_overrides.revision(scope.game_id, scope.player_id)


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
