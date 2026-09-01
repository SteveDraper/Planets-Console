"""Idle-dock priority-point equality for pre-limit PQ/PPQ rows.

``prioritypointchange == 2 * (starbases - ships built)`` when the observed
delta lies on that even lattice. Gift, trade, capture, and unmatched loss
contribute 0 PP. Classic PBP and PLS have no idle-dock constraint. Post-limit
spend is not this module.
"""

from __future__ import annotations

from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import GameSettings


def is_idle_dock_queue(settings: GameSettings) -> bool:
    """PQ or PPQ with a shared ship-limit (not Classic PBP, not PLS)."""
    if settings.shiplimittype != 0:
        return False
    return bool(settings.productionqueue or settings.planetaryproductionqueue)


def idle_dock_pp_on_lattice_values(priority_points: int, starbases: int) -> bool:
    """True when observed PP is ``2 * (starbases - k)`` for integer k in ``[0, starbases]``."""
    if starbases < 0 or priority_points < 0 or priority_points % 2 != 0:
        return False
    idle_docks = priority_points // 2
    return idle_docks <= starbases


def idle_dock_pp_on_lattice(observation: InferenceObservation) -> bool:
    """True when observed PP is ``2 * (starbases - k)`` for integer k in ``[0, starbases]``."""
    return idle_dock_pp_on_lattice_values(
        observation.priority_point_delta,
        observation.starbases_owned,
    )


def should_enforce_idle_dock_pp_values(
    *,
    priority_point_delta: int,
    starbases_owned: int,
    planet_delta: int,
    starbase_delta: int,
    is_after_ship_limit: bool,
    settings: GameSettings,
) -> bool:
    """Lattice-gated idle-dock PP equality for public scoreboard fields."""
    if is_after_ship_limit:
        return False
    if not is_idle_dock_queue(settings):
        return False
    if planet_delta < 0 or starbase_delta < 0:
        return False
    return idle_dock_pp_on_lattice_values(priority_point_delta, starbases_owned)


def should_enforce_idle_dock_pp(
    observation: InferenceObservation,
    settings: GameSettings,
) -> bool:
    """Lattice-gated idle-dock PP equality for this row."""
    return should_enforce_idle_dock_pp_values(
        priority_point_delta=observation.priority_point_delta,
        starbases_owned=observation.starbases_owned,
        planet_delta=observation.planet_delta,
        starbase_delta=observation.starbase_delta,
        is_after_ship_limit=observation.is_after_ship_limit,
        settings=settings,
    )


def idle_dock_implied_ships_built_values(priority_points: int, starbases: int) -> int | None:
    """Ships built implied by idle-dock PP, or None when not on lattice."""
    if not idle_dock_pp_on_lattice_values(priority_points, starbases):
        return None
    return starbases - priority_points // 2


def idle_dock_implied_ships_built(observation: InferenceObservation) -> int | None:
    """Ships built implied by idle-dock PP, or None when not on lattice."""
    return idle_dock_implied_ships_built_values(
        observation.priority_point_delta,
        observation.starbases_owned,
    )


IDLE_DOCK_PP_EQUALITY_LABEL = (
    "priorityPointChange == 2 * (starbasesOwned - shipsBuilt) (idle-dock PP equality)"
)
