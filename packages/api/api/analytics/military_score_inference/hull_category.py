"""Inference hull category assignment for component prior lookup."""

from __future__ import annotations

from typing import Literal, get_args

from api.models.components import Hull

InferenceHullCategory = Literal[
    "true_freighter",
    "alchemy_ship",
    "carrier",
    "battleship",
    "torpedo_ship",
    "beam_ship",
    "weaponless_hull",
    "utility",
]

INFERENCE_HULL_CATEGORIES: tuple[InferenceHullCategory, ...] = get_args(InferenceHullCategory)

BATTLESHIP_MASS_THRESHOLD = 200

HULL_CATEGORY_OVERRIDES: dict[int, InferenceHullCategory] = {}


def _is_alchemy_hull(hull: Hull) -> bool:
    return "alchemy" in hull.special.lower()


def resolve_inference_hull_category(
    hull: Hull,
    *,
    beam_count: int = 0,
    launcher_count: int = 0,
) -> InferenceHullCategory:
    """Assign an inference hull category from hull spec and fitted weapon counts."""
    override = HULL_CATEGORY_OVERRIDES.get(hull.id)
    if override is not None:
        return override

    has_weapon_slots = hull.beams > 0 or hull.launchers > 0
    has_fighter_bays = hull.fighterbays > 0

    if not has_fighter_bays and hull.beams == 0 and hull.launchers == 0:
        return "true_freighter"

    if _is_alchemy_hull(hull):
        return "alchemy_ship"

    if has_fighter_bays:
        return "carrier"

    if has_weapon_slots and beam_count == 0 and launcher_count == 0:
        return "weaponless_hull"

    if hull.beams > 0 and hull.launchers > 0 and hull.mass > BATTLESHIP_MASS_THRESHOLD:
        return "battleship"

    if hull.launchers > 0:
        return "torpedo_ship"

    if hull.beams > 0:
        return "beam_ship"

    return "utility"


def slot_fill_pattern(
    hull: Hull,
    *,
    beam_count: int,
    launcher_count: int,
) -> str:
    """Return full or partial slot fill for component prior lookup."""
    beam_full = hull.beams == 0 or beam_count == hull.beams
    launcher_full = hull.launchers == 0 or launcher_count == hull.launchers
    if beam_full and launcher_full:
        return "full"
    return "partial"
