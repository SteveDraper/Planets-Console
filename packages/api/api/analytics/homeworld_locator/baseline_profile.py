"""Homeworld baseline profile matching."""

from __future__ import annotations

from collections.abc import Sequence, Set

from api.concepts.races import preferred_homeworld_temp_w
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import GameSettings
from api.models.planet import Planet


def matches_homeworld_baseline_profile(
    planet: Planet,
    *,
    owner_id: int,
    race_id: int,
    settings: GameSettings,
    starbase_planet_ids: Set[int],
    min_baseline_clans: int,
) -> bool:
    """True when ``planet`` matches the homeworld baseline profile for one slot."""
    if planet_is_planetoid(planet):
        return False
    if planet.ownerid != owner_id:
        return False
    if planet.clans < min_baseline_clans:
        return False
    if settings.homeworldhasstarbase and planet.id not in starbase_planet_ids:
        return False
    return planet.temp == preferred_homeworld_temp_w(race_id)


def unique_baseline_profile_match(
    planets: Sequence[Planet],
    *,
    owner_id: int,
    race_id: int,
    settings: GameSettings,
    starbase_planet_ids: Set[int],
    min_baseline_clans: int,
) -> Planet | None:
    """Return the sole baseline-profile match for ``owner_id``, else ``None``."""
    matches = [
        planet
        for planet in planets
        if matches_homeworld_baseline_profile(
            planet,
            owner_id=owner_id,
            race_id=race_id,
            settings=settings,
            starbase_planet_ids=starbase_planet_ids,
            min_baseline_clans=min_baseline_clans,
        )
    ]
    if len(matches) != 1:
        return None
    return matches[0]
