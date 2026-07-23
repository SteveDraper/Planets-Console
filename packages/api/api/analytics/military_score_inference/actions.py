"""Bounded aggregate action catalog for military score build inference."""

from dataclasses import dataclass, field, replace
from pathlib import Path

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARBASE_FIGHTERS,
    STANDARD_STARBASE_MAX_FIGHTERS,
)
from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateCatalogCaps,
    resolved_aggregate_cap,
)
from api.analytics.military_score_inference.aggregate_catalog_build import (
    build_aggregate_actions,
    residual_count_bound,
)
from api.analytics.military_score_inference.component_eligibility import (
    player_by_id,
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetTorpOverlay,
    FleetTorpOverlayDiagnostics,
    admitted_torp_ids_for_policy_step,
    apply_torp_misalignment_penalties_to_catalog,
    build_fleet_torp_overlay_diagnostics,
    effective_fleet_torp_overlay,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.prior_weights_catalog import (
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    TierOverflowBand,
    build_tier_aware_probability_buckets,
)
from api.analytics.military_score_inference.scoring import starbase_fighter_score_delta_2x
from api.analytics.military_score_inference.ship_build_combos import (
    ShipBuildComboConfig,
    generate_ship_build_combos,
)
from api.analytics.military_score_inference.tier_policy import (
    DEFAULT_NEAR_BEST_OBJECTIVE_THRESHOLD,
    InferenceTierPolicyStep,
    compute_aggregate_admission_caps,
    resolve_fleet_inference_tuning,
    resolve_tier_policies,
)
from api.concepts.races import (
    evil_empire_free_starbase_fighters_per_host_turn,
    is_evil_empire,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.player import Player

DEFAULT_INFERENCE_TIME_LIMIT_SECONDS = 20.0


@dataclass(frozen=True)
class ActionCatalogConfig(AggregateCatalogCaps):
    ship_build_combo_config: ShipBuildComboConfig | None = None


@dataclass(frozen=True)
class ActionCatalog:
    aggregate_actions: tuple[CandidateAction, ...]
    ship_build_combos: tuple[ShipBuildCombo, ...]
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]]
    policy_step_id: str = ""
    policy_step_index: int = 0
    ranking_heuristics: InferenceRankingHeuristics = field(
        default_factory=InferenceRankingHeuristics
    )
    admission_caps_by_action_id: dict[str, int] = field(default_factory=dict)
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = field(default_factory=dict)
    prior_weights_diagnostics: PriorWeightsDiagnostics | None = None
    fleet_torp_overlay_diagnostics: FleetTorpOverlayDiagnostics | None = None
    near_best_objective_threshold: int = DEFAULT_NEAR_BEST_OBJECTIVE_THRESHOLD

    @property
    def catalog_size(self) -> int:
        return len(self.aggregate_actions) + len(self.ship_build_combos)

    def diagnostics(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "catalog_size": self.catalog_size,
            "aggregate_action_count": len(self.aggregate_actions),
            "ship_build_combo_count": len(self.ship_build_combos),
            "policy_step_id": self.policy_step_id,
            "policy_step_index": self.policy_step_index,
            "bucketed_action_count": sum(
                1
                for action in self.aggregate_actions
                if action.id in self.probability_buckets_by_action_id
            ),
            "nearBestObjectiveThreshold": self.near_best_objective_threshold,
        }
        if self.prior_weights_diagnostics is not None:
            payload["priorWeights"] = self.prior_weights_diagnostics.to_payload()
        if self.fleet_torp_overlay_diagnostics is not None:
            payload["fleetTorpOverlay"] = self.fleet_torp_overlay_diagnostics.to_payload()
        return payload


def build_inference_problem(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    race_id: int | None = None,
    max_solutions: int | None = None,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    military_score_alpha: int = 0,
    fixed_combo_counts: dict[str, int] | None = None,
    combo_count_neighborhood: int = 0,
) -> InferenceProblem:
    aggregate_actions = catalog.aggregate_actions
    ship_build_combos = catalog.ship_build_combos
    if fixed_combo_counts:
        ship_build_combos = _apply_combo_count_constraints(
            ship_build_combos,
            fixed_combo_counts=fixed_combo_counts,
            neighborhood=combo_count_neighborhood,
        )
    return InferenceProblem(
        observation=observation,
        aggregate_actions=aggregate_actions,
        race_id=race_id,
        ship_build_combos=ship_build_combos,
        policy_step_id=catalog.policy_step_id,
        policy_step_index=catalog.policy_step_index,
        probability_buckets_by_action_id=catalog.probability_buckets_by_action_id,
        max_solutions=20 if max_solutions is None else max_solutions,
        time_limit_seconds=time_limit_seconds,
        military_score_alpha=military_score_alpha,
        ranking_heuristics=catalog.ranking_heuristics,
        admission_caps_by_action_id=catalog.admission_caps_by_action_id,
        tier_overflow_by_action_id=catalog.tier_overflow_by_action_id,
        near_best_objective_threshold=catalog.near_best_objective_threshold,
    )


def build_action_catalog_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    config: ActionCatalogConfig | None = None,
    policy_step: InferenceTierPolicyStep | None = None,
    policy_step_index: int = 0,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    prior_weights_base_dir: Path | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
) -> ActionCatalog:
    resolved_policy_step = policy_step
    if resolved_policy_step is None:
        resolved_policy_step = resolve_tier_policies()[0]
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        observation.player_id,
        resolved_policy_step,
        resolved_mask=resolved_mask,
    )
    player = player_by_id(turn, observation.player_id)
    generic_freighter_hull_ids = _generic_solver_freighter_hull_ids(
        catalog_context.hulls_by_id,
        catalog_context.buildable_hull_ids,
    )
    prior_catalog = resolve_prior_weights_catalog(
        observation,
        turn.settings,
        race_id=player.raceid,
        buildable_hull_ids=catalog_context.buildable_hull_ids,
        generic_freighter_hull_ids=generic_freighter_hull_ids,
        eligible_engine_ids=catalog_context.eligible_engine_ids,
        eligible_beam_ids=catalog_context.eligible_beam_ids,
        eligible_torp_ids=catalog_context.eligible_torp_ids,
        base_dir=prior_weights_base_dir,
    )
    return build_action_catalog(
        observation,
        hulls_by_id=catalog_context.hulls_by_id,
        engines_by_id=catalog_context.engines_by_id,
        beams_by_id=catalog_context.beams_by_id,
        torpedos_by_id=catalog_context.torpedos_by_id,
        buildable_hull_ids=catalog_context.buildable_hull_ids,
        eligible_engine_ids=catalog_context.eligible_engine_ids,
        eligible_beam_ids=catalog_context.eligible_beam_ids,
        eligible_torp_ids=catalog_context.eligible_torp_ids,
        config=config,
        prior_catalog=prior_catalog,
        turn=turn,
        player=player,
        policy_step=resolved_policy_step,
        policy_step_index=policy_step_index,
        policy_steps=resolve_tier_policies(),
        fleet_torp_overlay=fleet_torp_overlay,
    )


def _generic_solver_freighter_hull_ids(
    hulls_by_id: dict[int, Hull],
    buildable_hull_ids: frozenset[int],
) -> frozenset[int]:
    """True freighter hulls collapsed into the solver's generic freighter combo."""
    return frozenset(
        hull_id
        for hull_id in buildable_hull_ids
        if (hull := hulls_by_id.get(hull_id)) is not None
        and hull.fighterbays == 0
        and hull.launchers == 0
        and hull.beams == 0
    )


def build_action_catalog(
    observation: InferenceObservation,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
    eligible_engine_ids: frozenset[int],
    eligible_beam_ids: frozenset[int],
    eligible_torp_ids: frozenset[int],
    prior_catalog: PriorWeightsCatalog,
    config: ActionCatalogConfig | None = None,
    turn: TurnInfo | None = None,
    player: Player | None = None,
    policy_step: InferenceTierPolicyStep | None = None,
    policy_step_index: int = 0,
    policy_steps: tuple[InferenceTierPolicyStep, ...] | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
) -> ActionCatalog:
    resolved_policy_step = policy_step or resolve_tier_policies()[-1]
    catalog_config = config or ActionCatalogConfig()
    if turn is not None and player is None:
        player = player_by_id(turn, observation.player_id)
    prior_diagnostics = prior_catalog.diagnostics
    resolved_overlay = effective_fleet_torp_overlay(fleet_torp_overlay)
    fleet_tuning = resolve_fleet_inference_tuning()
    policy_ladder = policy_steps or resolve_tier_policies()
    admission_step_index = next(
        (index for index, step in enumerate(policy_ladder) if step.id == resolved_policy_step.id),
        policy_step_index,
    )
    admitted_torp_ids = admitted_torp_ids_for_policy_step(
        policy_step=resolved_policy_step,
        policy_step_index=admission_step_index,
        policy_steps=policy_ladder,
        eligible_torp_ids=eligible_torp_ids,
        overlay=resolved_overlay,
    )

    aggregate_actions, probability_buckets = build_aggregate_actions(
        observation,
        catalog_config,
        torpedos_by_id,
        eligible_torp_ids,
        resolved_policy_step.aggregate_allowlist,
        prior_catalog,
        admitted_torp_ids=admitted_torp_ids,
    )
    kept_actions: list[CandidateAction] = list(aggregate_actions)
    if turn is not None and player is not None:
        kept_actions.extend(
            _evil_empire_free_starbase_fighter_actions(
                observation,
                turn,
                catalog_config,
                player,
            )
        )

    ranking_heuristics = InferenceRankingHeuristics()
    admission_caps_raw = compute_aggregate_admission_caps(policy_ladder, policy_step_index)
    admission_caps_by_action_id: dict[str, int] = {}
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = {}
    for action in kept_actions:
        if action.id not in probability_buckets:
            continue
        admission_cap = resolved_aggregate_cap(action.id, admission_caps_raw)
        buckets, overflow_band = build_tier_aware_probability_buckets(
            probability_buckets[action.id],
            admission_cap=admission_cap,
            current_cap=action.upper_bound,
            overflow_marginal_weight=ranking_heuristics.tier_overflow_marginal_weight,
        )
        probability_buckets[action.id] = buckets
        if admission_cap is not None:
            admission_caps_by_action_id[action.id] = admission_cap
        if overflow_band is not None:
            tier_overflow_by_action_id[action.id] = overflow_band

    probability_buckets = apply_torp_misalignment_penalties_to_catalog(
        probability_buckets,
        overlay=resolved_overlay,
        tuning=fleet_tuning,
    )
    fleet_overlay_diagnostics = build_fleet_torp_overlay_diagnostics(
        overlay=resolved_overlay,
        tuning=fleet_tuning,
        policy_step=resolved_policy_step,
        admitted_torp_ids=admitted_torp_ids,
    )

    ship_build_combos = generate_ship_build_combos(
        observation,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
        config=catalog_config.ship_build_combo_config,
        prior_catalog=prior_catalog,
        beam_slot_counts=resolved_policy_step.beam_slot_counts,
        launcher_slot_counts=resolved_policy_step.launcher_slot_counts,
    )

    return ActionCatalog(
        aggregate_actions=tuple(kept_actions),
        ship_build_combos=ship_build_combos,
        probability_buckets_by_action_id=probability_buckets,
        policy_step_id=resolved_policy_step.id,
        policy_step_index=policy_step_index,
        ranking_heuristics=ranking_heuristics,
        admission_caps_by_action_id=admission_caps_by_action_id,
        tier_overflow_by_action_id=tier_overflow_by_action_id,
        prior_weights_diagnostics=prior_diagnostics,
        fleet_torp_overlay_diagnostics=fleet_overlay_diagnostics,
        near_best_objective_threshold=resolved_policy_step.near_best_objective_threshold,
    )


def _apply_combo_count_constraints(
    combos: tuple[ShipBuildCombo, ...],
    *,
    fixed_combo_counts: dict[str, int],
    neighborhood: int,
) -> tuple[ShipBuildCombo, ...]:
    constrained: list[ShipBuildCombo] = []
    for combo in combos:
        if combo.combo_id not in fixed_combo_counts:
            constrained.append(replace(combo, lower_bound=0, upper_bound=0))
            continue
        seed_count = fixed_combo_counts[combo.combo_id]
        if neighborhood <= 0:
            constrained.append(replace(combo, lower_bound=seed_count, upper_bound=seed_count))
            continue
        lower_bound = max(combo.lower_bound, max(0, seed_count - neighborhood))
        upper_bound = min(combo.upper_bound, seed_count + neighborhood)
        constrained.append(replace(combo, lower_bound=lower_bound, upper_bound=upper_bound))
    return tuple(constrained)


def _evil_empire_free_starbase_fighter_actions(
    observation: InferenceObservation,
    turn: TurnInfo,
    config: ActionCatalogConfig,
    player: Player,
) -> list[CandidateAction]:
    """High-probability free starbase fighters for Evil Empire when resources allow."""
    if not is_evil_empire(player.raceid):
        return []

    free_per_host_turn = evil_empire_free_starbase_fighters_per_host_turn(turn.settings)
    if free_per_host_turn <= 0 or observation.starbases_owned <= 0:
        return []

    host_turns_elapsed = max(0, observation.turn - 1)
    fighter_room_per_starbase = max(0, STANDARD_STARBASE_MAX_FIGHTERS - HOMEBASE_STARBASE_FIGHTERS)
    per_starbase_cap = min(
        free_per_host_turn * host_turns_elapsed,
        fighter_room_per_starbase,
    )
    count_upper = min(
        residual_count_bound(
            observation,
            starbase_fighter_score_delta_2x(),
            config.max_starbase_fighters,
        ),
        per_starbase_cap * observation.starbases_owned,
    )
    if count_upper <= 0:
        return []

    return [
        CandidateAction(
            id="evil_empire_free_starbase_fighters",
            label="Evil Empire free starbase fighters (likely)",
            score_delta_2x=starbase_fighter_score_delta_2x(),
            upper_bound=count_upper,
        )
    ]
