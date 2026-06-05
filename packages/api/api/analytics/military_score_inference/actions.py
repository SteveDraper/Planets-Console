"""Bounded candidate action catalog for military score build inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARBASE_FIGHTERS,
    STANDARD_STARBASE_MAX_FIGHTERS,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.scoring import (
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    loaded_ship_fighter_score_delta_2x,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)
from api.analytics.military_score_inference.ship_build_presets import (
    LOADOUT_PRESET_EMPTY,
    LOADOUT_PRESET_TORPEDOES,
    build_action_id,
    default_build_components,
    is_military_hull,
    ship_build_score_delta_2x,
    torpedo_preset_catalog_eligible,
)
from api.concepts.races import (
    evil_empire_free_starbase_fighters_per_host_turn,
    is_evil_empire,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.player import Player, Race

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
    default_ship_build_probability_weight: int = 80
    torpedo_ship_build_probability_weight: int = 85
    noisy_action_probability_weight: int = 10
    fighter_transfer_probability_weight: int = 15
    evil_empire_free_starbase_fighter_probability_weight: int = 75


@dataclass(frozen=True)
class ActionCatalog:
    actions: tuple[CandidateAction, ...]
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]]

    @property
    def catalog_size(self) -> int:
        return len(self.actions)

    def diagnostics(self) -> dict[str, object]:
        return {
            "catalog_size": self.catalog_size,
            "bucketed_action_count": sum(
                1 for action in self.actions if action.id in BUCKETED_ACTION_IDS
            ),
            "ship_build_action_count": sum(
                1 for action in self.actions if action.id.startswith("build_")
            ),
        }


def build_inference_problem(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    max_solutions: int = 20,
    time_limit_seconds: float = 1.0,
) -> InferenceProblem:
    return InferenceProblem(
        observation=observation,
        actions=catalog.actions,
        probability_buckets_by_action_id=catalog.probability_buckets_by_action_id,
        max_solutions=max_solutions,
        time_limit_seconds=time_limit_seconds,
    )


def parse_component_id_csv(component_ids: str) -> frozenset[int]:
    if not component_ids.strip():
        return frozenset()
    return frozenset(int(component_id) for component_id in component_ids.split(",") if component_id)


def buildable_hull_ids_for_player(turn: TurnInfo, player_id: int) -> frozenset[int]:
    player = _player_by_id(turn, player_id)
    race = _race_by_id_or_none(turn, player.raceid)
    active_hull_ids = parse_component_id_csv(player.activehulls)
    if race is not None:
        eligible_hull_ids = active_hull_ids & (
            parse_component_id_csv(race.hulls) | parse_component_id_csv(race.basehulls)
        )
    else:
        eligible_hull_ids = active_hull_ids
    turn_hull_ids = frozenset(turn.racehulls)
    catalog_hull_ids = frozenset(hull.id for hull in turn.hulls)
    return eligible_hull_ids & turn_hull_ids & catalog_hull_ids


def build_action_catalog_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    config: ActionCatalogConfig | None = None,
) -> ActionCatalog:
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}
    default_engine_id = min(engines_by_id) if engines_by_id else None
    buildable_hull_ids = buildable_hull_ids_for_player(turn, observation.player_id)
    return build_action_catalog(
        observation,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
        default_engine_id=default_engine_id,
        config=config,
        turn=turn,
    )


def build_action_catalog(
    observation: InferenceObservation,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
    default_engine_id: int | None,
    config: ActionCatalogConfig | None = None,
    turn: TurnInfo | None = None,
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
    actions.extend(
        _ship_build_actions(
            observation,
            catalog_config,
            hulls_by_id=hulls_by_id,
            engines_by_id=engines_by_id,
            beams_by_id=beams_by_id,
            torpedos_by_id=torpedos_by_id,
            buildable_hull_ids=buildable_hull_ids,
            default_engine_id=default_engine_id,
        )
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

    return ActionCatalog(
        actions=tuple(kept_actions),
        probability_buckets_by_action_id=probability_buckets,
    )


def _player_by_id(turn: TurnInfo, player_id: int) -> Player:
    if turn.player.id == player_id:
        return turn.player
    for player in turn.players:
        if player.id == player_id:
            return player
    raise ValueError(f"unknown player id: {player_id}")


def _race_by_id_or_none(turn: TurnInfo, race_id: int) -> Race | None:
    for race in turn.races:
        if race.id == race_id:
            return race
    return None


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
    player = _player_by_id(turn, observation.player_id)
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


def _ship_build_upper_bound(
    observation: InferenceObservation,
    *,
    is_warship: bool,
    is_freighter: bool,
) -> int:
    if is_warship:
        count_delta = max(0, observation.warship_delta)
    elif is_freighter:
        count_delta = max(0, observation.freighter_delta)
    else:
        return 0
    return min(count_delta, observation.starbases_owned)


def _ship_build_actions(
    observation: InferenceObservation,
    config: ActionCatalogConfig,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
    default_engine_id: int | None,
) -> list[CandidateAction]:
    if default_engine_id is None or default_engine_id not in engines_by_id:
        return []

    defaults = default_build_components(
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        default_engine_id=default_engine_id,
    )
    default_engine = defaults.engine
    default_beam = defaults.beam
    default_torpedo = defaults.torpedo
    if default_engine is None:
        return []

    actions: list[CandidateAction] = []

    for hull_id in sorted(buildable_hull_ids):
        hull = hulls_by_id.get(hull_id)
        if hull is None:
            continue

        is_warship = is_military_hull(hull)
        is_freighter = not is_warship
        build_upper_bound = _ship_build_upper_bound(
            observation,
            is_warship=is_warship,
            is_freighter=is_freighter,
        )
        if build_upper_bound <= 0:
            continue

        presets: list[tuple[str, int]] = [
            (LOADOUT_PRESET_EMPTY, config.default_ship_build_probability_weight),
        ]
        if torpedo_preset_catalog_eligible(hull, default_torpedo):
            presets.append(
                (LOADOUT_PRESET_TORPEDOES, config.torpedo_ship_build_probability_weight),
            )

        for preset_id, probability_weight in presets:
            armed_build = preset_id == LOADOUT_PRESET_TORPEDOES
            score_delta_2x = ship_build_score_delta_2x(
                hull,
                default_engine,
                default_beam,
                default_torpedo,
                beam_count=hull.beams if armed_build else 0,
                launcher_count=hull.launchers if armed_build else 0,
            )
            if score_delta_2x == 0:
                continue
            actions.append(
                CandidateAction(
                    id=build_action_id(hull_id, preset_id),
                    label=f"Build {hull.name} ({preset_id})",
                    score_delta_2x=score_delta_2x,
                    warship_delta=1 if is_warship else 0,
                    freighter_delta=1 if is_freighter else 0,
                    build_slot_usage=1,
                    upper_bound=build_upper_bound,
                    probability_weight=probability_weight,
                )
            )

    return actions


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
