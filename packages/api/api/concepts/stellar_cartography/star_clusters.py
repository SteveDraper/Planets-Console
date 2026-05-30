"""Star cluster classification and host-aligned radiation math."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Literal

from api.concepts.planet_connections.wells import max_travel_distance
from api.concepts.stellar_cartography.layers import (
    LAYER_NEUTRON_CLUSTERS,
    LAYER_STAR_CLUSTERS,
)
from api.models.space import Star

# Planets.nu client identifies neutron star bodies by lethal core radius (ly).
NEUTRON_STAR_CORE_RADIUS_MIN = 5
NEUTRON_STAR_CORE_RADIUS_MAX = 10

ClusterNeutronKind = Literal["radiation", "neutron", "ambiguous_mixed"]


def stars_grouped_by_name(stars: list[Star]) -> dict[str, list[Star]]:
    by_name: dict[str, list[Star]] = defaultdict(list)
    for star in stars:
        by_name[star.name].append(star)
    return dict(by_name)


def is_neutron_star_body(star: Star) -> bool:
    """True when the star body's lethal core radius matches the neutron profile."""
    return NEUTRON_STAR_CORE_RADIUS_MIN <= star.radius <= NEUTRON_STAR_CORE_RADIUS_MAX


def cluster_neutron_kind(bodies: list[Star]) -> ClusterNeutronKind:
    """Classify a named cluster from its constituent ``stars[]`` bodies.

    When some bodies match the neutron radius profile and others do not, the host
    does not document which halo rules apply; treat that **ambiguous mixed** case
    as neutron for console rendering until a clearer rule is confirmed.
    """
    if not bodies:
        return "radiation"
    neutron_bodies = sum(1 for body in bodies if is_neutron_star_body(body))
    if neutron_bodies == 0:
        return "radiation"
    if neutron_bodies == len(bodies):
        return "neutron"
    return "ambiguous_mixed"


def neutron_cluster_names(stars: list[Star]) -> set[str]:
    """Cluster names rendered on the neutron (neutrino halo) layer."""
    return {
        name
        for name, bodies in stars_grouped_by_name(stars).items()
        if cluster_neutron_kind(bodies) in ("neutron", "ambiguous_mixed")
    }


def star_cluster_layer(name: str, neutron_names: set[str]) -> str:
    if name in neutron_names:
        return LAYER_NEUTRON_CLUSTERS
    return LAYER_STAR_CLUSTERS


def halo_radius_ly(mass: int) -> float:
    if mass <= 0:
        return 0.0
    return math.sqrt(mass)


def is_lethal_at(x: int, y: int, body: Star) -> bool:
    return math.hypot(x - body.x, y - body.y) <= body.radius


def radiation_at(x: int, y: int, body: Star) -> int:
    """Halo radiation at map cell ``(x, y)``; 0 inside the lethal core or outside the halo."""
    dist = math.hypot(x - body.x, y - body.y)
    if dist <= body.radius:
        return 0
    halo = halo_radius_ly(body.mass)
    if dist >= halo:
        return 0
    return int(math.ceil((body.temp / 100) * (1.0 - dist / halo)))


def sum_radiation_at(x: int, y: int, bodies: list[Star]) -> int:
    return sum(radiation_at(x, y, body) for body in bodies)


# Planets.nu client: NeutrinoSpeedFactor = 1 + min(0.3, flux / 1000).
_NEUTRINO_MOVEMENT_BONUS_CAP = 0.3
_NEUTRINO_MOVEMENT_BONUS_FLUX_DENOMINATOR = 1000


def neutrino_movement_bonus_fraction(flux: int) -> float:
    """Fractional increase in movement range when starting a turn in neutrino flux."""
    if flux <= 0:
        return 0.0
    return min(_NEUTRINO_MOVEMENT_BONUS_CAP, flux / _NEUTRINO_MOVEMENT_BONUS_FLUX_DENOMINATOR)


def neutrino_movement_bonus_percent(flux: int) -> float:
    """Percent increase in movement range (30% cap at flux >= 300)."""
    return neutrino_movement_bonus_fraction(flux) * 100.0


def format_neutrino_movement_bonus(flux: int) -> str:
    """Hover label for magnitude-dependent movement range bonus."""
    percent = neutrino_movement_bonus_percent(flux)
    if percent == int(percent):
        return f"+{int(percent)}%"
    return f"+{percent:.1f}%"


def neutrino_max_range_at_warp_9(flux: int) -> float:
    """Regular (non-gravitonic) movement range at warp 9 with neutrino boost."""
    return max_travel_distance(9, gravitonic_movement=False) * (
        1.0 + neutrino_movement_bonus_fraction(flux)
    )


def format_neutrino_warp_9_max_range(flux: int) -> str:
    """Parenthetical hover suffix: ``84.4 ly at warp 9``."""
    ly = neutrino_max_range_at_warp_9(flux)
    if ly == int(ly):
        return f"{int(ly)} ly at warp 9"
    return f"{ly:.1f} ly at warp 9"
