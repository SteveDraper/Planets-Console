"""Debris-disk seed radius on the map plane."""

from __future__ import annotations

from api.models.planet import Planet


def debris_disk_seed_radius(planet: Planet) -> int | None:
    """Border radius of a debris-disk seed, or ``None`` when the planet is not a seed.

    Seeds store radius in ``debrisdisk`` (values > 1). Traditional planets are 0;
    planetoids inside a disk are 1.
    """
    if planet.debrisdisk <= 1:
        return None
    return planet.debrisdisk
