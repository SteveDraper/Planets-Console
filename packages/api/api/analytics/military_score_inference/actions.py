"""Bounded aggregate action catalog for military score build inference."""

from dataclasses import dataclass, field, replace

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARBASE_FIGHTERS,
    STANDARD_STARBASE_MAX_FIGHTERS,
)
from api.analytics.military_score_inference.aggregate_action_registry import (
    BUCKETED_ACTION_IDS,
    base_buckets_for_action,
)
from api.analytics.military_score_inference.component_eligibility import (
    player_by_id,
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.prior_weights import (
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.prior_weights_laplace import laplace_log_weight
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    TierOverflowBand,
    admission_cap_for_action,
    build_tier_aware_probability_buckets,
)
from api.analytics.military_score_inference.scoring import (
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    loaded_ship_fighter_score_delta_2x,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)
from api.analytics.military_score_inference.ship_build_combos import (
    ShipBuildComboConfig,
    generate_ship_build_combos,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    compute_aggregate_admission_caps,
    resolve_tier_policies,
    resolved_aggregate_cap,
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
class ActionCatalogConfig:
    max_planet_defense_posts: int = 100
    max_starbase_defense_posts: int = 100
    max_starbase_fighters: int = 200
    max_ship_fighters: int = 500
    max_ship_torpedoes_per_type: int = 200
    max_fighter_transfers: int = 50
    ship_build_combo_config: ShipBuildComboConfig | None = None
    noisy_action_probability_weight: int = 10
    fighter_transfer_probability_weight: int = 15
    evil_empire_free_starbase_fighter_pseudo_count: float = 500


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
    prior_weights: PriorWeightsDiagnostics | None = None

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
                1 for action in self.aggregate_actions if action.id in BUCKETED_ACTION_IDS
            ),
        }
        if self.prior_weights is not None:
            payload["priorWeights"] = self.prior_weights.to_payload()
        return payload


def build_inference_problem(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
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
    )


def build_action_catalog_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    config: ActionCatalogConfig | None = None,
    policy_step: InferenceTierPolicyStep | None = None,
    policy_step_index: int = 0,
    resolved_mask: ResolvedHullCatalogMask | None = None,
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
    prior_catalog = resolve_prior_weights_catalog(
        observation,
        turn.settings,
        race_id=player.raceid,
        buildable_hull_ids=catalog_context.buildable_hull_ids,
        eligible_engine_ids=catalog_context.eligible_engine_ids,
        eligible_beam_ids=catalog_context.eligible_beam_ids,
        eligible_torp_ids=catalog_context.eligible_torp_ids,
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
        turn=turn,
        player=player,
        prior_catalog=prior_catalog,
        policy_step=resolved_policy_step,
        policy_step_index=policy_step_index,
        policy_steps=resolve_tier_policies(),
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
    config: ActionCatalogConfig | None = None,
    turn: TurnInfo | None = None,
    player: Player | None = None,
    prior_catalog: PriorWeightsCatalog | None = None,
    policy_step: InferenceTierPolicyStep | None = None,
    policy_step_index: int = 0,
    policy_steps: tuple[InferenceTierPolicyStep, ...] | None = None,
) -> ActionCatalog:
    resolved_policy_step = policy_step or resolve_tier_policies()[-1]
    catalog_config = config or ActionCatalogConfig()
    if turn is not None and player is None:
        player = player_by_id(turn, observation.player_id)
    prior_diagnostics = prior_catalog.diagnostics if prior_catalog is not None else None

    actions: list[CandidateAction] = []
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]] = {}

    actions.extend(
        _aggregate_noisy_actions(
            observation,
            catalog_config,
            torpedos_by_id,
            resolved_policy_step.aggregate_allowlist,
        )
    )
    if turn is not None and player is not None:
        actions.extend(
            _evil_empire_free_starbase_fighter_actions(
                observation,
                turn,
                catalog_config,
                player,
            )
        )

    kept_actions: list[CandidateAction] = []
    for action in actions:
        if action.upper_bound <= 0:
            continue
        updated_action, base_buckets = _aggregate_action_with_prior(action, prior_catalog)
        kept_actions.append(updated_action)
        if base_buckets is not None:
            probability_buckets[action.id] = base_buckets

    policy_ladder = policy_steps or resolve_tier_policies()
    ranking_heuristics = InferenceRankingHeuristics()
    admission_caps_raw = compute_aggregate_admission_caps(policy_ladder, policy_step_index)
    admission_caps_by_action_id: dict[str, int] = {}
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = {}
    for action in kept_actions:
        if action.id not in probability_buckets:
            continue
        admission_cap = admission_cap_for_action(action.id, admission_caps_raw)
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
        prior_weights=prior_catalog,
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
        prior_weights=prior_diagnostics,
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


def _residual_count_bound(
    observation: InferenceObservation,
    score_delta_2x: int,
    configured_cap: int,
) -> int:
    if score_delta_2x == 0:
        return 0
    if observation.military_delta_2x == 0:
        return 0

    abs_score = abs(score_delta_2x)
    abs_residual = abs(observation.military_delta_2x) + observation.military_partition_slack_2x
    return min(configured_cap, abs_residual // abs_score)


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
        _residual_count_bound(
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
            probability_weight=laplace_log_weight(
                config.evil_empire_free_starbase_fighter_pseudo_count,
                total=config.evil_empire_free_starbase_fighter_pseudo_count,
                cell_count=1,
                scale=INFERENCE_PROBABILITY_WEIGHT_SCALE,
            ),
        )
    ]


def _aggregate_noisy_actions(
    observation: InferenceObservation,
    config: ActionCatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
    aggregate_allowlist: dict[str, int],
) -> list[CandidateAction]:
    actions: list[CandidateAction] = []

    fine_grained_candidates = [
        CandidateAction(
            id="planet_defense_posts_added_total",
            label="Planet defense posts added",
            score_delta_2x=planet_defense_post_score_delta_2x(),
            upper_bound=_residual_count_bound(
                observation,
                planet_defense_post_score_delta_2x(),
                config.max_planet_defense_posts,
            ),
            probability_weight=config.noisy_action_probability_weight,
        ),
        CandidateAction(
            id="starbase_defense_posts_added_total",
            label="Starbase defense posts added",
            score_delta_2x=starbase_defense_post_score_delta_2x(),
            upper_bound=_residual_count_bound(
                observation,
                starbase_defense_post_score_delta_2x(),
                config.max_starbase_defense_posts,
            ),
            probability_weight=config.noisy_action_probability_weight,
        ),
        CandidateAction(
            id="starbase_fighters_added_total",
            label="Starbase fighters added",
            score_delta_2x=starbase_fighter_score_delta_2x(),
            upper_bound=_residual_count_bound(
                observation,
                starbase_fighter_score_delta_2x(),
                config.max_starbase_fighters,
            ),
            probability_weight=config.noisy_action_probability_weight,
        ),
        CandidateAction(
            id="ship_fighters_added_total",
            label="Ship fighters added",
            score_delta_2x=loaded_ship_fighter_score_delta_2x(),
            upper_bound=_residual_count_bound(
                observation,
                loaded_ship_fighter_score_delta_2x(),
                config.max_ship_fighters,
            ),
            probability_weight=config.noisy_action_probability_weight,
        ),
    ]
    for torpedo_id in sorted(torpedos_by_id):
        torpedo = torpedos_by_id[torpedo_id]
        per_torpedo_score = loaded_ship_torpedo_score_delta_2x(torpedo.torpedocost)
        fine_grained_candidates.append(
            CandidateAction(
                id=f"ship_torps_loaded_{torpedo_id}",
                label=f"Ship torpedoes loaded ({torpedo.name})",
                score_delta_2x=per_torpedo_score,
                upper_bound=_residual_count_bound(
                    observation,
                    per_torpedo_score,
                    config.max_ship_torpedoes_per_type,
                ),
                probability_weight=config.noisy_action_probability_weight,
            )
        )

    transfer_cap = min(
        config.max_fighter_transfers,
        _residual_count_bound(
            observation,
            STARBASE_FIGHTER_SCORE_DELTA_2X,
            config.max_fighter_transfers,
        ),
    )
    fine_grained_candidates.extend(
        [
            CandidateAction(
                id="fighters_starbase_to_ship",
                label="Fighters transferred starbase to ship",
                score_delta_2x=STARBASE_FIGHTER_SCORE_DELTA_2X,
                upper_bound=transfer_cap,
                probability_weight=config.fighter_transfer_probability_weight,
            ),
            CandidateAction(
                id="fighters_ship_to_starbase",
                label="Fighters transferred ship to starbase",
                score_delta_2x=-STARBASE_FIGHTER_SCORE_DELTA_2X,
                upper_bound=transfer_cap,
                probability_weight=config.fighter_transfer_probability_weight,
            ),
        ]
    )

    for action in fine_grained_candidates:
        allowlist_cap = resolved_aggregate_cap(action.id, aggregate_allowlist)
        if allowlist_cap is None:
            continue
        capped_upper = min(action.upper_bound, allowlist_cap)
        if capped_upper <= 0:
            continue
        actions.append(replace(action, upper_bound=capped_upper))

    return actions


def _aggregate_action_with_prior(
    action: CandidateAction,
    prior_catalog: PriorWeightsCatalog | None,
) -> tuple[CandidateAction, tuple[ProbabilityBucket, ...] | None]:
    updated_action = action
    if prior_catalog is not None:
        prior_weight = prior_catalog.aggregate_probability_weight(action.id)
        if prior_weight is not None:
            updated_action = replace(action, probability_weight=prior_weight)

    base_buckets = base_buckets_for_action(action.id)

    if base_buckets is not None and prior_catalog is not None:
        base_buckets = prior_catalog.probability_buckets_for_action(
            action.id,
            base_buckets,
        )
    return updated_action, base_buckets
