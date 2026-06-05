"""Bounded aggregate action catalog for military score build inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARBASE_FIGHTERS,
    STANDARD_STARBASE_MAX_FIGHTERS,
)
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
    eligible_component_ids_for_player,
    player_by_id,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ProbabilityBucket,
    ShipBuildCombo,
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
    DEFAULT_SHIP_BUILD_TIER,
    ShipBuildComboConfig,
    generate_ship_build_combos,
)
from api.concepts.races import (
    evil_empire_free_starbase_fighters_per_host_turn,
    is_evil_empire,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo

PLANET_DEFENSE_POST_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 10, 100),
    ProbabilityBucket("heavy build-up", 11, 50, 20),
    ProbabilityBucket("extreme build-up", 51, 100, 5),
)
STARBASE_DEFENSE_POST_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 10, 100),
    ProbabilityBucket("heavy build-up", 11, 50, 20),
    ProbabilityBucket("extreme build-up", 51, 100, 5),
)
STARBASE_FIGHTER_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 20, 80),
    ProbabilityBucket("heavy build-up", 21, 100, 15),
    ProbabilityBucket("extreme build-up", 101, 200, 3),
)
SHIP_FIGHTER_BUCKETS = (
    ProbabilityBucket("modest load", 0, 20, 70),
    ProbabilityBucket("heavy load", 21, 100, 20),
    ProbabilityBucket("extreme load", 101, 500, 5),
)
SHIP_TORPEDO_BUCKETS = (
    ProbabilityBucket("modest load", 0, 20, 70),
    ProbabilityBucket("heavy load", 21, 100, 20),
    ProbabilityBucket("extreme load", 101, 200, 5),
)

DEFAULT_INFERENCE_TIME_LIMIT_SECONDS = 20.0
LARGE_COMBO_CATALOG_MAX_SOLUTIONS_ONE_THRESHOLD = 5000

BUCKETED_ACTION_IDS = frozenset(
    {
        "planet_defense_posts_added_total",
        "starbase_defense_posts_added_total",
        "starbase_fighters_added_total",
        "ship_fighters_added_total",
    }
)


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
    evil_empire_free_starbase_fighter_probability_weight: int = 75


@dataclass(frozen=True)
class ActionCatalog:
    aggregate_actions: tuple[CandidateAction, ...]
    ship_build_combos: tuple[ShipBuildCombo, ...]
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]]
    ship_build_tier: int = DEFAULT_SHIP_BUILD_TIER

    @property
    def catalog_size(self) -> int:
        return len(self.aggregate_actions) + len(self.ship_build_combos)

    def diagnostics(self) -> dict[str, object]:
        return {
            "catalog_size": self.catalog_size,
            "aggregate_action_count": len(self.aggregate_actions),
            "ship_build_combo_count": len(self.ship_build_combos),
            "ship_build_tier": self.ship_build_tier,
            "bucketed_action_count": sum(
                1 for action in self.aggregate_actions if action.id in BUCKETED_ACTION_IDS
            ),
        }


def build_inference_problem(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    max_solutions: int | None = None,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> InferenceProblem:
    resolved_max_solutions = max_solutions
    if resolved_max_solutions is None:
        resolved_max_solutions = (
            1
            if len(catalog.ship_build_combos) > LARGE_COMBO_CATALOG_MAX_SOLUTIONS_ONE_THRESHOLD
            else 20
        )
    return InferenceProblem(
        observation=observation,
        aggregate_actions=catalog.aggregate_actions,
        ship_build_combos=catalog.ship_build_combos,
        ship_build_tier=catalog.ship_build_tier,
        probability_buckets_by_action_id=catalog.probability_buckets_by_action_id,
        max_solutions=resolved_max_solutions,
        time_limit_seconds=time_limit_seconds,
    )


def build_action_catalog_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    config: ActionCatalogConfig | None = None,
    ship_build_tier: int = DEFAULT_SHIP_BUILD_TIER,
) -> ActionCatalog:
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}
    buildable_hull_ids = buildable_hull_ids_for_player(turn, observation.player_id)
    player = player_by_id(turn, observation.player_id)
    eligible_engine_ids = eligible_component_ids_for_player(
        turn,
        observation.player_id,
        active_component_csv=player.activeengines,
        turn_catalog_ids=frozenset(engines_by_id),
    )
    eligible_beam_ids = eligible_component_ids_for_player(
        turn,
        observation.player_id,
        active_component_csv=player.activebeams,
        turn_catalog_ids=frozenset(beams_by_id),
    )
    eligible_torp_ids = eligible_component_ids_for_player(
        turn,
        observation.player_id,
        active_component_csv=player.activetorps,
        turn_catalog_ids=frozenset(torpedos_by_id),
    )
    return build_action_catalog(
        observation,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
        config=config,
        turn=turn,
        ship_build_tier=ship_build_tier,
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
    ship_build_tier: int = DEFAULT_SHIP_BUILD_TIER,
) -> ActionCatalog:
    catalog_config = config or ActionCatalogConfig()
    actions: list[CandidateAction] = []
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]] = {}

    actions.extend(_aggregate_noisy_actions(observation, catalog_config, torpedos_by_id))
    if turn is not None:
        actions.extend(
            _evil_empire_free_starbase_fighter_actions(observation, turn, catalog_config)
        )
    actions.extend(
        _fighter_transfer_actions(observation, catalog_config),
    )

    kept_actions: list[CandidateAction] = []
    for action in actions:
        if action.upper_bound <= 0:
            continue
        kept_actions.append(action)
        if action.id in BUCKETED_ACTION_IDS:
            probability_buckets[action.id] = _probability_buckets_for_action(action.id)
        elif action.id.startswith("ship_torps_loaded_"):
            probability_buckets[action.id] = SHIP_TORPEDO_BUCKETS

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
    )

    return ActionCatalog(
        aggregate_actions=tuple(kept_actions),
        ship_build_combos=ship_build_combos,
        probability_buckets_by_action_id=probability_buckets,
        ship_build_tier=ship_build_tier,
    )


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
    abs_residual = abs(observation.military_delta_2x)
    return min(configured_cap, abs_residual // abs_score)


def _evil_empire_free_starbase_fighter_actions(
    observation: InferenceObservation,
    turn: TurnInfo,
    config: ActionCatalogConfig,
) -> list[CandidateAction]:
    """High-probability free starbase fighters for Evil Empire when resources allow."""
    player = player_by_id(turn, observation.player_id)
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
            probability_weight=config.evil_empire_free_starbase_fighter_probability_weight,
        )
    ]


def _aggregate_noisy_actions(
    observation: InferenceObservation,
    config: ActionCatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
) -> list[CandidateAction]:
    actions = [
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
        actions.append(
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
    return actions


def _fighter_transfer_actions(
    observation: InferenceObservation,
    config: ActionCatalogConfig,
) -> list[CandidateAction]:
    transfer_cap = min(
        config.max_fighter_transfers,
        _residual_count_bound(
            observation,
            STARBASE_FIGHTER_SCORE_DELTA_2X,
            config.max_fighter_transfers,
        ),
    )
    return [
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


def _probability_buckets_for_action(action_id: str) -> tuple[ProbabilityBucket, ...]:
    if action_id == "planet_defense_posts_added_total":
        return PLANET_DEFENSE_POST_BUCKETS
    if action_id == "starbase_defense_posts_added_total":
        return STARBASE_DEFENSE_POST_BUCKETS
    if action_id == "starbase_fighters_added_total":
        return STARBASE_FIGHTER_BUCKETS
    if action_id == "ship_fighters_added_total":
        return SHIP_FIGHTER_BUCKETS
    raise ValueError(f"no probability buckets configured for action {action_id}")
