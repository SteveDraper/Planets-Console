"""Factored ship build combo generation for military score inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.models import InferenceObservation, ShipBuildCombo
from api.analytics.military_score_inference.ship_build_scoring import (
    ship_build_counts_as_warship,
    ship_build_military_score_delta_2x,
)
from api.analytics.military_score_inference.tier_policy import SlotCountMode
from api.models.components import Beam, Engine, Hull, Torpedo

GENERIC_FREIGHTER_COMBO_ID = "combo_freighter"
GENERIC_ZERO_MILITARY_SCORE_LABEL = "Freighter"


def is_generic_zero_military_score_combo_id(combo_id: str) -> bool:
    return combo_id == GENERIC_FREIGHTER_COMBO_ID


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


def beam_count_options_for_slot_mode(hull: Hull, slot_mode: SlotCountMode) -> tuple[int, ...]:
    if hull.beams == 0:
        return (0,)
    if slot_mode == "partial":
        return tuple(range(0, hull.beams + 1))
    return (0, hull.beams)


def launcher_count_options_for_slot_mode(hull: Hull, slot_mode: SlotCountMode) -> tuple[int, ...]:
    if hull.launchers == 0:
        return (0,)
    if slot_mode == "partial":
        return tuple(range(0, hull.launchers + 1))
    return (0, hull.launchers)


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


def _generic_freighter_combo(
    *,
    upper_bound: int,
    probability_weight: int,
) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=GENERIC_FREIGHTER_COMBO_ID,
        hull_id=0,
        engine_id=0,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=(GENERIC_ZERO_MILITARY_SCORE_LABEL,),
        score_delta_2x=0,
        freighter_delta=1,
        upper_bound=upper_bound,
        probability_weight=probability_weight,
    )


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
    beam_slot_counts: SlotCountMode = "none",
    launcher_slot_counts: SlotCountMode = "none",
) -> tuple[ShipBuildCombo, ...]:
    combo_config = config or ShipBuildComboConfig()
    combos: list[ShipBuildCombo] = []
    freighter_upper_bound = 0

    for hull_id in sorted(buildable_hull_ids):
        hull = hulls_by_id.get(hull_id)
        if hull is None:
            continue

        beam_count_options = beam_count_options_for_slot_mode(hull, beam_slot_counts)
        launcher_count_options = launcher_count_options_for_slot_mode(hull, launcher_slot_counts)

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
                            counts_as_warship = ship_build_counts_as_warship(
                                hull,
                                beam_count=beam_count,
                                launcher_count=launcher_count,
                            )
                            counts_as_freighter = not counts_as_warship
                            build_upper_bound = ship_build_upper_bound(
                                observation,
                                is_warship=counts_as_warship,
                                is_freighter=counts_as_freighter,
                            )
                            if build_upper_bound <= 0:
                                continue

                            score_delta_2x = ship_build_military_score_delta_2x(
                                hull,
                                engine,
                                beam,
                                torpedo,
                                beam_count=beam_count,
                                launcher_count=launcher_count,
                            )
                            if score_delta_2x == 0:
                                freighter_upper_bound = max(
                                    freighter_upper_bound, build_upper_bound
                                )
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
                                    hull_beam_slots=hull.beams,
                                    hull_launcher_slots=hull.launchers,
                                    labels=(
                                        ship_build_combo_label(
                                            hull,
                                            engine,
                                            beam,
                                            torpedo,
                                            beam_count=beam_count,
                                            launcher_count=launcher_count,
                                        ),
                                    ),
                                    score_delta_2x=score_delta_2x,
                                    warship_delta=1 if counts_as_warship else 0,
                                    freighter_delta=1 if counts_as_freighter else 0,
                                    upper_bound=build_upper_bound,
                                    probability_weight=probability_weight,
                                )
                            )

    if freighter_upper_bound > 0:
        combos.append(
            _generic_freighter_combo(
                upper_bound=freighter_upper_bound,
                probability_weight=combo_config.default_probability_weight,
            )
        )

    pruned = prune_combos_for_observation(
        observation,
        tuple(combos),
        max_aggregate_residual_when_ship_builds=combo_config.max_aggregate_residual_when_ship_builds,
    )
    return pruned


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
    kept = [
        combo
        for combo in combos
        if combo.upper_bound > 0
        and (combo.score_delta_2x > 0 or combo.warship_delta > 0 or combo.freighter_delta > 0)
    ]
    required_builds = observation.warship_delta + observation.freighter_delta
    if required_builds > 0 and max_aggregate_residual_when_ship_builds is not None:
        score_floor = abs_military_delta - max_aggregate_residual_when_ship_builds
        narrowed = [
            combo
            for combo in kept
            if combo.score_delta_2x >= score_floor
            or combo.warship_delta > 0
            or combo.freighter_delta > 0
        ]
        if narrowed:
            kept = narrowed
    return tuple(kept)
