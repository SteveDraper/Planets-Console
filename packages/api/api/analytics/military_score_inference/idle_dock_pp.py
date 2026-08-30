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


def idle_dock_pp_on_lattice(observation: InferenceObservation) -> bool:
    """True when observed PP is ``2 * (starbases - k)`` for integer k in ``[0, starbases]``."""
    priority_points = observation.priority_point_delta
    starbases = observation.starbases_owned
    if starbases < 0 or priority_points < 0 or priority_points % 2 != 0:
        return False
    idle_docks = priority_points // 2
    return idle_docks <= starbases


def should_enforce_idle_dock_pp(
    observation: InferenceObservation,
    settings: GameSettings,
) -> bool:
    """Lattice-gated idle-dock PP equality for this row."""
    if observation.is_after_ship_limit:
        return False
    if not is_idle_dock_queue(settings):
        return False
    if observation.planet_delta < 0 or observation.starbase_delta < 0:
        return False
    return idle_dock_pp_on_lattice(observation)


def idle_dock_implied_ships_built(observation: InferenceObservation) -> int | None:
    """Ships built implied by idle-dock PP, or None when not on lattice."""
    if not idle_dock_pp_on_lattice(observation):
        return None
    return observation.starbases_owned - observation.priority_point_delta // 2


IDLE_DOCK_PP_EQUALITY_LABEL = (
    "priorityPointChange == 2 * (starbasesOwned - shipsBuilt) (idle-dock PP equality)"
)
