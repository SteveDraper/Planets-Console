"""Finish-mode state machine and step diagnostics for one policy-ladder tier."""

from __future__ import annotations

import time
from enum import Enum

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.collision_hull_widen import (
    CollisionHullWidenPlan,
)
from api.analytics.military_score_inference.component_eligibility import (
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_admission import (
    maybe_early_stop_after_step,
    maybe_no_new_exact_signatures_early_stop,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.prior_fleet_tech_raise import (
    PriorFleetTechRaisePlan,
)
from api.analytics.military_score_inference.tier_emission_ledger import (
    tier_emission_fields,
)
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep
from api.models.game import TurnInfo


class TierStepFinishMode(Enum):
    """How ``finish_tier_step`` closes the step after appending diagnostics."""

    DIAGNOSTICS_ONLY = "diagnostics_only"
    """Append diagnostics; caller owns ladder completion (cancel / invalid / abort)."""

    SKIP = "skip"
    """Advance index + ship-only early-stop (widen / raise skip paths)."""

    COMPLETE = "complete"
    """Advance index + ship-only and no-new-signatures early-stops (happy path)."""

    BUDGET_STOP = "budget_stop"
    """Advance index with no early-stop (tier allowance exhausted)."""


def _policy_step_diagnostics(
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    catalog: ActionCatalog | None,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    band_residual_2x: int | None,
    emission_fields: dict[str, object] | None = None,
    collision_widen: CollisionHullWidenPlan | None = None,
    prior_fleet_tech_raise: PriorFleetTechRaisePlan | None = None,
) -> dict[str, object]:
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        observation.player_id,
        policy_step,
    )
    diagnostics: dict[str, object] = {
        "policyStepId": policy_step.id,
        "policyStepIndex": policy_step_index,
        "policyStepsAttempted": policy_step_index + 1,
        "constraintSnapshot": policy_step.constraint_snapshot(),
        "resolvedEligibleEngineIds": sorted(catalog_context.eligible_engine_ids),
        "resolvedEligibleBeamIds": sorted(catalog_context.eligible_beam_ids),
        "resolvedEligibleTorpIds": sorted(catalog_context.eligible_torp_ids),
        "resolvedBuildableHullIds": sorted(catalog_context.buildable_hull_ids),
        "alpha": policy_step.alpha,
        "comboCount": len(catalog.ship_build_combos) if catalog is not None else 0,
        "seedCount": seed_count,
        "bandResidual2x": band_residual_2x,
        "allowShipOnlyExactEarlyStop": policy_step.allow_ship_only_exact_early_stop,
        "hullCollisionTwinWiden": policy_step.hull_collision_twin_widen,
        "runDegradeAggregateProbe": policy_step.run_degrade_aggregate_probe,
    }
    if emission_fields is not None:
        diagnostics.update(emission_fields)
    if collision_widen is not None:
        diagnostics.update(collision_widen.to_diagnostics())
    if prior_fleet_tech_raise is not None:
        diagnostics.update(prior_fleet_tech_raise.to_diagnostics())
    return diagnostics


def _annotate_last_step_early_stop(state: PolicyLadderState) -> None:
    reason = state.ladder_early_stop_reason
    if reason is None or not state.step_diagnostics:
        return
    state.step_diagnostics[-1]["ladderEarlyStopReason"] = reason


def finish_tier_step(
    state: PolicyLadderState,
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    catalog: ActionCatalog | None,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    band_residual_2x: int | None,
    step_started_at: float,
    held_count_before: int,
    newly_admitted: list[InferenceSolution],
    collision_widen: CollisionHullWidenPlan | None = None,
    prior_fleet_tech_raise: PriorFleetTechRaisePlan | None = None,
    skipped: bool = False,
    finish_mode: TierStepFinishMode = TierStepFinishMode.DIAGNOSTICS_ONLY,
    tier_allowance_seconds: float | None = None,
    reserved_for_later_seconds: float | None = None,
    spendable_seconds: float | None = None,
    added_combo_ids: frozenset[str] = frozenset(),
    added_aggregate_action_ids: frozenset[str] = frozenset(),
    new_exact_before_step: int | None = None,
) -> None:
    """Append tier diagnostics, then advance / early-stop per ``finish_mode``."""
    state.step_diagnostics.append(
        _policy_step_diagnostics(
            policy_step=policy_step,
            policy_step_index=policy_step_index,
            catalog=catalog,
            turn=turn,
            observation=observation,
            seed_count=seed_count,
            band_residual_2x=band_residual_2x,
            emission_fields=tier_emission_fields(
                duration_ms=(time.monotonic() - step_started_at) * 1000.0,
                held_count_before=held_count_before,
                held_count_after=len(state.merged_solutions),
                newly_admitted=newly_admitted,
                time_limited=state.time_limited,
                last_status=state.last_status,
                skipped=skipped,
                tier_allowance_seconds=tier_allowance_seconds,
                reserved_for_later_seconds=reserved_for_later_seconds,
                spendable_seconds=spendable_seconds,
            ),
            collision_widen=collision_widen,
            prior_fleet_tech_raise=prior_fleet_tech_raise,
        )
    )
    if finish_mode is TierStepFinishMode.DIAGNOSTICS_ONLY:
        return

    state.next_step_index = policy_step_index + 1

    if finish_mode in (TierStepFinishMode.SKIP, TierStepFinishMode.COMPLETE):
        if maybe_early_stop_after_step(
            state,
            policy_step=policy_step,
            observation=observation,
            catalog=catalog,
        ):
            _annotate_last_step_early_stop(state)
            return
    if finish_mode is TierStepFinishMode.COMPLETE:
        if new_exact_before_step is None:
            raise RuntimeError("finish_tier_step COMPLETE requires new_exact_before_step")
        if maybe_no_new_exact_signatures_early_stop(
            state,
            added_combo_ids=added_combo_ids,
            added_aggregate_action_ids=added_aggregate_action_ids,
            new_exact_before_step=new_exact_before_step,
        ):
            _annotate_last_step_early_stop(state)
            return
    # BUDGET_STOP: advance only -- no early-stop.

    if state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True
