"""Ground truth explanation extraction for inference corpus cases (v1)."""

from collections import Counter
from dataclasses import dataclass

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)
from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_label
from api.analytics.military_score_inference.ship_build_scoring import ship_build_score_delta_2x
from api.models.components import Torpedo
from api.models.game import TurnInfo
from api.models.player import Score

from tests.inference_corpus.models import COMPLEXITY_ORDINAL, ComplexityLevel
from tests.inference_corpus.ship_inventory import (
    beams_by_id,
    describe_new_ship_build,
    engines_by_id,
    fighter_load_delta,
    hulls_by_id,
    new_owned_ships,
    new_ship_load_action_counts,
    planet_defense_inventory_delta,
    ship_to_build_combo_id,
    starbase_defense_inventory_delta,
    starbase_fighter_inventory_delta,
    starbase_fighters_for_owner,
    torpedo_load_delta_by_type,
    total_loaded_fighters,
)
from tests.inference_corpus.ship_inventory import (
    torpedos_by_id as torpedos_by_id_from_turn,
)

GroundTruth = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class GroundTruthExtraction:
    available: bool
    ground_truth: GroundTruth = ()
    unavailable_reason: str | None = None


def extract_ground_truth_v1(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    complexity: ComplexityLevel,
) -> GroundTruthExtraction:
    """Build a normalized action multiset when v1 rules apply."""
    if complexity == "adjunct" or COMPLEXITY_ORDINAL[complexity] > COMPLEXITY_ORDINAL["heavy"]:
        return GroundTruthExtraction(
            available=False,
            unavailable_reason="complexity_out_of_scope",
        )

    ship_build_ids = _extract_ship_build_combo_ids(prior_turn, score_turn, player_id)
    if ship_build_ids is None:
        return GroundTruthExtraction(
            available=False,
            unavailable_reason="ship_build_combo_unmapped",
        )

    new_ships = new_owned_ships(prior_turn, score_turn, player_id)
    new_ship_ids = frozenset(ship.id for ship in new_ships)

    multiset: Counter[str] = Counter()
    for action_id in ship_build_ids:
        multiset[action_id] += 1
    multiset.update(new_ship_load_action_counts(new_ships, score_turn))

    observation = build_inference_observation(score, score_turn)
    explained_2x = sum(
        _catalog_score_delta_2x_for_action_id(action_id, score_turn) * multiset[action_id]
        for action_id in multiset
    )
    residual_2x = observation.military_delta_2x - explained_2x
    if residual_2x < 0:
        return GroundTruthExtraction(
            available=False,
            unavailable_reason="residual_unexplained",
        )

    aggregate_result = _allocate_aggregate_residual(
        prior_turn,
        score_turn,
        player_id,
        residual_2x=residual_2x,
        torpedos_by_id={torp.id: torp for torp in score_turn.torpedos},
        exclude_ship_ids=new_ship_ids,
    )
    if aggregate_result is None:
        if residual_2x == 0:
            return GroundTruthExtraction(available=True, ground_truth=_sorted_multiset(multiset))
        return GroundTruthExtraction(
            available=False,
            unavailable_reason="residual_unexplained",
        )

    multiset.update(aggregate_result)
    return GroundTruthExtraction(available=True, ground_truth=_sorted_multiset(multiset))


def format_ground_truth_summary(
    ground_truth: GroundTruth,
    *,
    score_turn: TurnInfo,
) -> str:
    """Render a ground-truth multiset as human-readable build/load text."""
    if not ground_truth:
        return "no modeled activity"

    torpedos_by_id = {torp.id: torp for torp in score_turn.torpedos}
    parts: list[str] = []

    for action_id, count in ground_truth:
        if action_id.startswith("combo_"):
            label = _combo_ground_truth_label(action_id, score_turn)
            parts.append(f"{count}x {label}" if count != 1 else label)
            continue
        if action_id == "ship_fighters_added_total":
            parts.append(f"loaded {count} ship fighter{'s' if count != 1 else ''}")
            continue
        if action_id.startswith("ship_torps_loaded_"):
            torp_id = int(action_id.removeprefix("ship_torps_loaded_"))
            torp = torpedos_by_id.get(torp_id)
            torp_name = torp.name if torp is not None else f"torp {torp_id}"
            parts.append(f"loaded {count} {torp_name} torp{'s' if count != 1 else ''} on ships")
            continue
        if action_id == "starbase_fighters_added_total":
            parts.append(f"added {count} starbase fighter{'s' if count != 1 else ''}")
            continue
        if action_id == "starbase_defense_posts_added_total":
            parts.append(f"added {count} starbase defense post{'s' if count != 1 else ''}")
            continue
        if action_id == "planet_defense_posts_added_total":
            parts.append(f"added {count} planet defense post{'s' if count != 1 else ''}")
            continue
        if action_id == "fighters_starbase_to_ship":
            parts.append(f"transferred {count} fighter{'s' if count != 1 else ''} starbase to ship")
            continue
        if action_id == "fighters_ship_to_starbase":
            parts.append(f"transferred {count} fighter{'s' if count != 1 else ''} ship to starbase")
            continue
        parts.append(f"{action_id} x{count}")

    return ", ".join(parts)


def describe_inventory_activity(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
) -> str:
    """Best-effort human summary from inventory deltas when strict ground truth fails."""
    new_ships = new_owned_ships(prior_turn, score_turn, player_id)
    new_ship_ids = frozenset(ship.id for ship in new_ships)
    parts: list[str] = [describe_new_ship_build(ship, score_turn) for ship in new_ships]

    fighter_delta = fighter_load_delta(
        prior_turn,
        score_turn,
        player_id,
        exclude_ship_ids=new_ship_ids,
    )
    if fighter_delta > 0:
        parts.append(
            f"loaded {fighter_delta} fighter{'s' if fighter_delta != 1 else ''} on existing ships"
        )

    torp_map = torpedos_by_id_from_turn(score_turn)
    for torp_id, torp_delta in sorted(
        torpedo_load_delta_by_type(
            prior_turn,
            score_turn,
            player_id,
            exclude_ship_ids=new_ship_ids,
        ).items()
    ):
        torp = torp_map.get(torp_id)
        torp_name = torp.name if torp is not None else f"torp {torp_id}"
        parts.append(f"loaded {torp_delta}x {torp_name} on existing ships")

    starbase_fighter_delta = starbase_fighter_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_fighter_delta > 0:
        parts.append(f"starbase fighters +{starbase_fighter_delta}")

    starbase_defense_delta = starbase_defense_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_defense_delta > 0:
        parts.append(f"starbase defense +{starbase_defense_delta}")

    planet_defense_delta = planet_defense_inventory_delta(prior_turn, score_turn, player_id)
    if planet_defense_delta > 0:
        parts.append(f"planet defense +{planet_defense_delta}")

    return ", ".join(parts) if parts else "no inventory changes detected"


def format_unavailable_ground_truth(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    reason: str,
) -> str:
    """Fallback summary when strict ground truth cannot be built."""
    activity = describe_inventory_activity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
    )
    if activity == "no inventory changes detected":
        return f"ground truth unavailable ({reason})"
    return f"{activity} (strict ground truth unavailable: {reason})"


def _sorted_multiset(counter: Counter[str]) -> GroundTruth:
    return tuple(sorted((action_id, count) for action_id, count in counter.items() if count > 0))


def _extract_ship_build_combo_ids(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
) -> list[str] | None:
    action_ids: list[str] = []
    for ship in new_owned_ships(prior_turn, score_turn, player_id):
        combo_id = ship_to_build_combo_id(ship, score_turn)
        if combo_id is None:
            return None
        action_ids.append(combo_id)
    return action_ids


def _parse_combo_id(
    combo_id: str,
) -> tuple[int, int, int | None, int | None, int, int] | None:
    if not combo_id.startswith("combo_"):
        return None
    parts = combo_id.removeprefix("combo_").split("_")
    if len(parts) != 6:
        return None
    hull_id = int(parts[0])
    engine_id = int(parts[1])
    beam_id = None if parts[2] == "none" else int(parts[2])
    torp_id = None if parts[3] == "none" else int(parts[3])
    beam_count = int(parts[4])
    launcher_count = int(parts[5])
    return hull_id, engine_id, beam_id, torp_id, beam_count, launcher_count


def _combo_ground_truth_label(combo_id: str, turn: TurnInfo) -> str:
    parsed = _parse_combo_id(combo_id)
    if parsed is None:
        return combo_id
    hull_id, engine_id, beam_id, torp_id, beam_count, launcher_count = parsed
    hull = hulls_by_id(turn).get(hull_id)
    engine = engines_by_id(turn).get(engine_id)
    beam = beams_by_id(turn).get(beam_id) if beam_id is not None else None
    torpedo = torpedos_by_id_from_turn(turn).get(torp_id) if torp_id is not None else None
    if hull is None or engine is None:
        return combo_id
    return ship_build_combo_label(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _combo_score_delta_2x(combo_id: str, turn: TurnInfo) -> int:
    parsed = _parse_combo_id(combo_id)
    if parsed is None:
        return 0
    hull_id, engine_id, beam_id, torp_id, beam_count, launcher_count = parsed
    hull = hulls_by_id(turn).get(hull_id)
    engine = engines_by_id(turn).get(engine_id)
    if hull is None or engine is None:
        return 0
    beam = beams_by_id(turn).get(beam_id) if beam_id is not None else None
    torpedo = torpedos_by_id_from_turn(turn).get(torp_id) if torp_id is not None else None
    return ship_build_score_delta_2x(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _catalog_score_delta_2x_for_action_id(action_id: str, turn: TurnInfo) -> int:
    if action_id.startswith("combo_"):
        return _combo_score_delta_2x(action_id, turn)
    if action_id == "ship_fighters_added_total":
        return LOADED_SHIP_FIGHTER_SCORE_DELTA_2X
    if action_id.startswith("ship_torps_loaded_"):
        torp_id = int(action_id.removeprefix("ship_torps_loaded_"))
        torp = next((candidate for candidate in turn.torpedos if candidate.id == torp_id), None)
        if torp is None:
            return 0
        return loaded_ship_torpedo_score_delta_2x(torp.torpedocost)
    if action_id == "starbase_fighters_added_total":
        return starbase_fighter_score_delta_2x()
    if action_id == "starbase_defense_posts_added_total":
        return starbase_defense_post_score_delta_2x()
    if action_id == "planet_defense_posts_added_total":
        return planet_defense_post_score_delta_2x()
    if action_id in {"fighters_starbase_to_ship", "fighters_ship_to_starbase"}:
        return starbase_fighter_score_delta_2x()
    return 0


def _allocate_aggregate_residual(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    *,
    residual_2x: int,
    torpedos_by_id: dict[int, Torpedo],
    exclude_ship_ids: frozenset[int] = frozenset(),
) -> Counter[str] | None:
    if residual_2x == 0:
        return Counter()

    remaining = residual_2x
    allocated: Counter[str] = Counter()

    ship_fighter_delta = fighter_load_delta(
        prior_turn, score_turn, player_id, exclude_ship_ids=exclude_ship_ids
    )
    if ship_fighter_delta > 0 and remaining >= LOADED_SHIP_FIGHTER_SCORE_DELTA_2X:
        count = min(ship_fighter_delta, remaining // LOADED_SHIP_FIGHTER_SCORE_DELTA_2X)
        if count > 0:
            allocated["ship_fighters_added_total"] += count
            remaining -= count * LOADED_SHIP_FIGHTER_SCORE_DELTA_2X

    for torp_id in sorted(torpedos_by_id):
        torp = torpedos_by_id[torp_id]
        unit = loaded_ship_torpedo_score_delta_2x(torp.torpedocost)
        if unit <= 0:
            continue
        torp_delta = torpedo_load_delta_by_type(
            prior_turn, score_turn, player_id, exclude_ship_ids=exclude_ship_ids
        ).get(torp_id, 0)
        if torp_delta <= 0 or remaining < unit:
            continue
        count = min(torp_delta, remaining // unit)
        if count > 0:
            allocated[f"ship_torps_loaded_{torp_id}"] += count
            remaining -= count * unit

    starbase_fighter_delta = starbase_fighter_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_fighter_delta > 0 and remaining >= starbase_fighter_score_delta_2x():
        count = min(starbase_fighter_delta, remaining // starbase_fighter_score_delta_2x())
        if count > 0:
            allocated["starbase_fighters_added_total"] += count
            remaining -= count * starbase_fighter_score_delta_2x()

    starbase_defense_delta = starbase_defense_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_defense_delta > 0 and remaining >= starbase_defense_post_score_delta_2x():
        count = min(starbase_defense_delta, remaining // starbase_defense_post_score_delta_2x())
        if count > 0:
            allocated["starbase_defense_posts_added_total"] += count
            remaining -= count * starbase_defense_post_score_delta_2x()

    planet_defense_delta = planet_defense_inventory_delta(prior_turn, score_turn, player_id)
    if planet_defense_delta > 0 and remaining >= planet_defense_post_score_delta_2x():
        count = min(planet_defense_delta, remaining // planet_defense_post_score_delta_2x())
        if count > 0:
            allocated["planet_defense_posts_added_total"] += count
            remaining -= count * planet_defense_post_score_delta_2x()

    transfer = _fighter_transfer_counts(prior_turn, score_turn, player_id)
    if transfer is not None:
        direction, count = transfer
        unit = starbase_fighter_score_delta_2x()
        if count > 0 and remaining >= count * unit:
            allocated[direction] += count
            remaining -= count * unit

    if remaining != 0:
        return None
    return allocated


def _fighter_transfer_counts(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
) -> tuple[str, int] | None:
    prior_ship = total_loaded_fighters(prior_turn, player_id)
    score_ship = total_loaded_fighters(score_turn, player_id)
    prior_base = starbase_fighters_for_owner(prior_turn, player_id)
    score_base = starbase_fighters_for_owner(score_turn, player_id)
    ship_delta = score_ship - prior_ship
    base_delta = score_base - prior_base
    if ship_delta > 0 and base_delta < 0 and ship_delta == -base_delta:
        return ("fighters_starbase_to_ship", ship_delta)
    if ship_delta < 0 and base_delta > 0 and -ship_delta == base_delta:
        return ("fighters_ship_to_starbase", base_delta)
    return None
