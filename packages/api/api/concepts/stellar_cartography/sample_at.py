"""Sample Stellar Cartography features at a map cell (host-aligned tooltip math)."""

from __future__ import annotations

import math
from collections import defaultdict

from api.analytics.stellar_cartography import ion_storm_class
from api.concepts.stellar_cartography.layers import (
    LAYER_BLACK_HOLES,
    LAYER_ION_STORMS,
    LAYER_NEBULAE,
    LAYER_NEUTRON_CLUSTERS,
    LAYER_STAR_CLUSTERS,
    PAINT_ORDER,
)
from api.concepts.stellar_cartography.star_clusters import (
    format_neutrino_movement_bonus,
    format_neutrino_warp_9_max_range,
    is_lethal_at,
    neutron_cluster_names,
    stars_grouped_by_name,
    sum_radiation_at,
)
from api.models.game import TurnInfo
from api.models.space import IonStorm, Nebula

ION_CLASS_NAMES: dict[int, str] = {
    1: "Harmless",
    2: "Moderate",
    3: "Strong",
    4: "Dangerous",
    5: "Very dangerous",
}

# Host-aligned tooltip math (Planets.nu client / Meteor's Library).
NEBULA_VISIBILITY_NUMERATOR = 4000
NEBULA_VISIBILITY_MAX_LY = 250


def _distance_ly(x: int, y: int, fx: int, fy: int) -> float:
    return math.hypot(x - fx, y - fy)


def _ion_storm_groups(ionstorms: list[IonStorm]) -> list[list[IonStorm]]:
    by_parent: dict[int, list[IonStorm]] = defaultdict(list)
    roots: list[IonStorm] = []
    for storm in ionstorms:
        if storm.parentid == 0:
            roots.append(storm)
        else:
            by_parent[storm.parentid].append(storm)
    return [[root, *by_parent.get(root.id, [])] for root in roots]


def _ion_voltage_at(circles: list[IonStorm], x: int, y: int, *, cloudy: bool) -> float:
    if not cloudy:
        center = circles[0]
        if _distance_ly(x, y, center.x, center.y) <= center.radius:
            return float(center.voltage)
        return 0.0

    total = 0.0
    for circle in circles:
        dist = _distance_ly(x, y, circle.x, circle.y)
        if dist <= circle.radius and circle.radius > 0:
            total += circle.voltage * (1.0 - dist / circle.radius)
    return total


def _ion_storm_entries(turn: TurnInfo, x: int, y: int) -> list[dict]:
    entries: list[dict] = []
    cloudy = turn.settings.nuionstorms
    for group in _ion_storm_groups(turn.ionstorms):
        voltage = _ion_voltage_at(group, x, y, cloudy=cloudy)
        if voltage <= 0:
            continue
        mev = int(round(voltage))
        storm_class = ion_storm_class(mev)
        class_name = ION_CLASS_NAMES.get(storm_class, ION_CLASS_NAMES[1])
        entries.append(
            {
                "layer": LAYER_ION_STORMS,
                "lines": [f"Class {storm_class} {class_name}", f"{mev} V"],
            }
        )
    return entries


def _star_cluster_entries(turn: TurnInfo, x: int, y: int) -> list[dict]:
    by_name = stars_grouped_by_name(turn.stars)
    neutron_names = neutron_cluster_names(turn.stars)

    entries: list[dict] = []
    for name, bodies in by_name.items():
        layer = LAYER_NEUTRON_CLUSTERS if name in neutron_names else LAYER_STAR_CLUSTERS
        lethal_lines = [
            f"{name} — lethal — temp {body.temp}" for body in bodies if is_lethal_at(x, y, body)
        ]
        if lethal_lines:
            for line in lethal_lines:
                entries.append({"layer": layer, "lines": [line]})
            continue

        total_radiation = sum_radiation_at(x, y, bodies)
        if total_radiation <= 0:
            continue
        if layer == LAYER_NEUTRON_CLUSTERS:
            bonus = format_neutrino_movement_bonus(total_radiation)
            warp_9 = format_neutrino_warp_9_max_range(total_radiation)
            line = f"{name} — neutrino flux {total_radiation} — movement {bonus} ({warp_9})"
        else:
            line = f"{name} — radiation {total_radiation}"
        entries.append({"layer": layer, "lines": [line]})
    return entries


def _black_hole_max_warp(coreradius: int, bandradius: int, dist: float) -> int | None:
    """Map ergosphere depth to max safe warp (9 outer bands, 1 inner)."""
    if dist <= coreradius or dist > bandradius:
        return None
    width = bandradius - coreradius
    if width <= 0:
        return None
    depth = (bandradius - dist) / width
    band = min(9, max(1, math.ceil(depth * 9)))
    return 10 - band


def _black_hole_entries(turn: TurnInfo, x: int, y: int) -> list[dict]:
    entries: list[dict] = []
    for hole in turn.blackholes:
        dist = _distance_ly(x, y, hole.x, hole.y)
        if dist <= hole.coreradius:
            label = f"Lethal ({hole.name})" if hole.name else "Lethal"
            entries.append({"layer": LAYER_BLACK_HOLES, "lines": [label]})
            continue
        max_warp = _black_hole_max_warp(hole.coreradius, hole.bandradius, dist)
        if max_warp is not None:
            entries.append(
                {
                    "layer": LAYER_BLACK_HOLES,
                    "lines": [f"Max warp: {max_warp}"],
                }
            )
    return entries


def _nebula_density_at(centers: list[Nebula], x: int, y: int) -> float:
    total = 0.0
    for center in centers:
        if center.radius <= 0 or center.id < 0:
            continue
        dist = _distance_ly(x, y, center.x, center.y)
        if dist <= center.radius:
            total += math.ceil(center.intensity * (1.0 - dist / center.radius))
    return total


def _nebula_visibility_ly(density: float) -> int | None:
    if density <= 0:
        return None
    return min(
        NEBULA_VISIBILITY_MAX_LY,
        int(round(NEBULA_VISIBILITY_NUMERATOR / (density + 1))),
    )


def _nebula_entries(turn: TurnInfo, x: int, y: int) -> list[dict]:
    by_name: dict[str, list[Nebula]] = defaultdict(list)
    for nebula in turn.nebulas:
        by_name[nebula.name or "Nebula"].append(nebula)

    entries: list[dict] = []
    for name, centers in by_name.items():
        density = _nebula_density_at(centers, x, y)
        visibility = _nebula_visibility_ly(density)
        if visibility is None:
            continue
        entries.append(
            {
                "layer": LAYER_NEBULAE,
                "lines": [name, f"{visibility} ly"],
            }
        )
    return entries


def sample_at(turn: TurnInfo, x: int, y: int) -> dict:
    """Return stacked tooltip entries at map cell ``(x, y)`` in paint order."""
    star_entries = _star_cluster_entries(turn, x, y)
    by_layer: dict[str, list[dict]] = {
        LAYER_NEBULAE: _nebula_entries(turn, x, y),
        LAYER_ION_STORMS: _ion_storm_entries(turn, x, y),
        LAYER_STAR_CLUSTERS: [
            entry for entry in star_entries if entry["layer"] == LAYER_STAR_CLUSTERS
        ],
        LAYER_NEUTRON_CLUSTERS: [
            entry for entry in star_entries if entry["layer"] == LAYER_NEUTRON_CLUSTERS
        ],
        LAYER_BLACK_HOLES: _black_hole_entries(turn, x, y),
    }
    entries: list[dict] = []
    for layer in PAINT_ORDER:
        entries.extend(by_layer[layer])
    return {"x": x, "y": y, "entries": entries}
