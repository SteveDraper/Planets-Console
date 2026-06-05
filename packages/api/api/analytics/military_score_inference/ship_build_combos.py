"""Factored ship build combo generation for military score inference."""

from collections import defaultdict
from dataclasses import dataclass, replace

from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
    eligible_component_ids_for_player,
)
from api.analytics.military_score_inference.models import InferenceObservation, ShipBuildCombo
from api.analytics.military_score_inference.ship_build_presets import (
    is_military_hull,
    ship_build_score_delta_2x,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo

# Tier 3: active engines, beams, and torps (jump to turn catalog when active lists are empty).
DEFAULT_SHIP_BUILD_TIER = 3


@dataclass(frozen=True)
class ShipBuildComboConfig:
    default_probability_weight: int = 80
    armed_probability_weight: int = 85
    max_aggregate_residual_when_ship_builds: int | None = 1000


def ship_build_combo_id(
    *,
    hull_id: int,
    engine_id: int,
    beam_id: int | None,
    torp_id: int | None,
    beam_count: int,
    launcher_count: int,
) -> str:
    beam_part = str(beam_id) if beam_id is not None else "none"
    torp_part = str(torp_id) if torp_id is not None else "none"
    return f"combo_{hull_id}_{engine_id}_{beam_part}_{torp_part}_{beam_count}_{launcher_count}"


def ship_build_combo_label(
    hull: Hull,
    engine: Engine,
    beam: Beam | None,
    torpedo: Torpedo | None,
    *,
    beam_count: int,
    launcher_count: int,
) -> str:
    components: list[str] = []
    if hull.engines > 0:
        components.append(f"{hull.engines}x {engine.name}")
    if beam_count > 0 and beam is not None:
        components.append(f"{beam_count}x {beam.name}")
    if launcher_count > 0 and torpedo is not None:
        launcher_word = "launcher" if launcher_count == 1 else "launchers"
        components.append(f"{launcher_count}x {torpedo.name} {launcher_word}")
    if components:
        return f"Build {hull.name}: {', '.join(components)}"
    return f"Build {hull.name} (unarmed)"


def ship_build_upper_bound(
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


def generate_ship_build_combos(
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
    config: ShipBuildComboConfig | None = None,
) -> tuple[ShipBuildCombo, ...]:
    combo_config = config or ShipBuildComboConfig()
    combos: list[ShipBuildCombo] = []

    for hull_id in sorted(buildable_hull_ids):
        hull = hulls_by_id.get(hull_id)
        if hull is None:
            continue

        is_warship = is_military_hull(hull)
        is_freighter = not is_warship
        build_upper_bound = ship_build_upper_bound(
            observation,
            is_warship=is_warship,
            is_freighter=is_freighter,
        )
        if build_upper_bound <= 0:
            continue

        beam_count_options = (0,) if hull.beams == 0 else (0, hull.beams)
        launcher_count_options = (0,) if hull.launchers == 0 else (0, hull.launchers)

        for engine_id in sorted(eligible_engine_ids):
            engine = engines_by_id.get(engine_id)
            if engine is None:
                continue

            for beam_count in beam_count_options:
                beam_choices: tuple[Beam | None, ...]
                if beam_count == 0:
                    beam_choices = (None,)
                else:
                    beam_choices = tuple(
                        beams_by_id[beam_id]
                        for beam_id in sorted(eligible_beam_ids)
                        if beam_id in beams_by_id
                    )
                    if not beam_choices:
                        continue

                for launcher_count in launcher_count_options:
                    torp_choices: tuple[Torpedo | None, ...]
                    if launcher_count == 0:
                        torp_choices = (None,)
                    else:
                        torp_choices = tuple(
                            torpedos_by_id[torp_id]
                            for torp_id in sorted(eligible_torp_ids)
                            if torp_id in torpedos_by_id
                        )
                        if not torp_choices:
                            continue

                    for beam in beam_choices:
                        for torpedo in torp_choices:
                            score_delta_2x = ship_build_score_delta_2x(
                                hull,
                                engine,
                                beam,
                                torpedo,
                                beam_count=beam_count,
                                launcher_count=launcher_count,
                            )
                            if score_delta_2x == 0:
                                continue

                            armed = beam_count > 0 or launcher_count > 0
                            probability_weight = (
                                combo_config.armed_probability_weight
                                if armed
                                else combo_config.default_probability_weight
                            )
                            combos.append(
                                ShipBuildCombo(
                                    combo_id=ship_build_combo_id(
                                        hull_id=hull_id,
                                        engine_id=engine_id,
                                        beam_id=beam.id if beam is not None else None,
                                        torp_id=torpedo.id if torpedo is not None else None,
                                        beam_count=beam_count,
                                        launcher_count=launcher_count,
                                    ),
                                    hull_id=hull_id,
                                    engine_id=engine_id,
                                    beam_id=beam.id if beam is not None else None,
                                    torp_id=torpedo.id if torpedo is not None else None,
                                    beam_count=beam_count,
                                    launcher_count=launcher_count,
                                    label=ship_build_combo_label(
                                        hull,
                                        engine,
                                        beam,
                                        torpedo,
                                        beam_count=beam_count,
                                        launcher_count=launcher_count,
                                    ),
                                    score_delta_2x=score_delta_2x,
                                    warship_delta=1 if is_warship else 0,
                                    freighter_delta=1 if is_freighter else 0,
                                    upper_bound=build_upper_bound,
                                    probability_weight=probability_weight,
                                )
                            )

    pruned = prune_combos_for_observation(
        observation,
        tuple(combos),
        max_aggregate_residual_when_ship_builds=combo_config.max_aggregate_residual_when_ship_builds,
    )
    return merge_score_equivalent_combos(pruned)


def prune_combos_for_observation(
    observation: InferenceObservation,
    combos: tuple[ShipBuildCombo, ...],
    *,
    max_aggregate_residual_when_ship_builds: int | None = 1000,
) -> tuple[ShipBuildCombo, ...]:
    """Drop combos that cannot contribute to a non-negative count solution."""
    if observation.military_delta_2x <= 0:
        return combos
    abs_military_delta = observation.military_delta_2x
    kept = [combo for combo in combos if combo.upper_bound > 0 and combo.score_delta_2x > 0]
    required_builds = observation.warship_delta + observation.freighter_delta
    if required_builds > 0 and max_aggregate_residual_when_ship_builds is not None:
        score_floor = abs_military_delta - max_aggregate_residual_when_ship_builds
        narrowed = [combo for combo in kept if combo.score_delta_2x >= score_floor]
        if narrowed:
            kept = narrowed
    return tuple(kept)


def merge_score_equivalent_combos(
    combos: tuple[ShipBuildCombo, ...],
) -> tuple[ShipBuildCombo, ...]:
    """Merge combos that share score and ship-count vectors for CP-SAT feasibility."""
    groups: dict[tuple[int, int, int], list[ShipBuildCombo]] = defaultdict(list)
    for combo in combos:
        groups[(combo.score_delta_2x, combo.warship_delta, combo.freighter_delta)].append(combo)

    merged: list[ShipBuildCombo] = []
    for members in groups.values():
        representative = max(members, key=lambda combo: (combo.probability_weight, combo.combo_id))
        if len(members) == 1:
            merged.append(representative)
            continue
        merged.append(
            replace(
                representative,
                combo_id=(
                    f"combo_equiv_{representative.score_delta_2x}_"
                    f"{representative.warship_delta}_{representative.freighter_delta}"
                ),
            )
        )
    return tuple(merged)


def generate_ship_build_combos_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    config: ShipBuildComboConfig | None = None,
    ship_build_tier: int = DEFAULT_SHIP_BUILD_TIER,
) -> tuple[ShipBuildCombo, ...]:
    del ship_build_tier  # tier escalation is handled in a follow-on ticket
    player = turn.player if turn.player.id == observation.player_id else None
    if player is None:
        for candidate in turn.players:
            if candidate.id == observation.player_id:
                player = candidate
                break
    if player is None:
        return ()

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}

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

    return generate_ship_build_combos(
        observation,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids_for_player(turn, observation.player_id),
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
        config=config,
    )
