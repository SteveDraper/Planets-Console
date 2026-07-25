"""Visibility coverage assembly: scan origins and hybrid overlays.

Game-domain helpers for the Visibility analytic. Origins are the viewpoint
player plus Share Intel partners. Ship-scan and Sensor Sweep kinds use nebula
``V(P)`` / Nebula Scanner modulation; minefield detection is ideal disks only
(nebulae do not shrink mine detect range).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from api.concepts.diplomacy import share_intel_partner_ids
from api.concepts.hull_abilities import hull_has_nebula_scanner
from api.concepts.map_region_coverage import (
    CoverageOrigin,
    MapRegionOverlay,
    build_hybrid_coverage,
    hybrid_coverage_to_overlay,
)
from api.concepts.ship_missions import (
    is_mine_sweep_mission,
    is_sensor_sweep_or_bioscan_mission,
)
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.player import Relation
from api.models.ship import Ship
from api.models.space import Nebula

# Host "Sensor mission range" default when no GameSettings field exists.
DEFAULT_SENSOR_MISSION_RANGE_LY = 200.0

# Host "Minefield detect range" default (Nu SweepMines uses 200; no turn settings key).
DEFAULT_MINEFIELD_DETECT_RANGE_LY = 200.0

KIND_SHIP_SCAN = "ship-scan"
KIND_ACTIVE_SENSOR_SWEEP = "active-sensor-sweep"
KIND_POTENTIAL_SENSOR_SWEEP = "potential-sensor-sweep"
KIND_ACTIVE_MINEFIELD_DETECT = "active-minefield-detect"
KIND_POTENTIAL_MINEFIELD_DETECT = "potential-minefield-detect"

# Wire defaults; SPA may override with client preferences.
DEFAULT_KIND_FILL_COLORS: Mapping[str, str] = {
    KIND_SHIP_SCAN: "#38bdf8",
    KIND_ACTIVE_SENSOR_SWEEP: "#a78bfa",
    KIND_POTENTIAL_SENSOR_SWEEP: "#fbbf24",
    KIND_ACTIVE_MINEFIELD_DETECT: "#34d399",
    KIND_POTENTIAL_MINEFIELD_DETECT: "#fb7185",
}
DEFAULT_FILL_OPACITY = 0.28

# Paint order: ship-scan under potentials under actives.
VISIBILITY_KIND_Z_ORDER: tuple[str, ...] = (
    KIND_SHIP_SCAN,
    KIND_POTENTIAL_SENSOR_SWEEP,
    KIND_POTENTIAL_MINEFIELD_DETECT,
    KIND_ACTIVE_SENSOR_SWEEP,
    KIND_ACTIVE_MINEFIELD_DETECT,
)

# Kinds that ignore nebula V(P) / Nebula Scanner (ideal disks only).
_DISK_ONLY_KINDS: frozenset[str] = frozenset(
    {
        KIND_ACTIVE_MINEFIELD_DETECT,
        KIND_POTENTIAL_MINEFIELD_DETECT,
    }
)


def visibility_owner_ids(
    viewpoint_player_id: int,
    relations: Iterable[Relation],
) -> frozenset[int]:
    """Viewpoint plus Share Intel (or Full Alliance) partners."""
    return frozenset({viewpoint_player_id}) | share_intel_partner_ids(
        relations, viewpoint_player_id
    )


def _hull_by_id(hulls: Sequence[Hull]) -> dict[int, Hull]:
    return {hull.id: hull for hull in hulls}


def _ship_origins(
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    base_range: float,
    mission_predicate: Callable[[int], bool] | None = None,
    apply_nebula_scanner: bool = True,
) -> list[CoverageOrigin]:
    hull_map = _hull_by_id(hulls)
    origins: list[CoverageOrigin] = []
    for ship in ships:
        if ship.ownerid not in owner_ids:
            continue
        if mission_predicate is not None and not mission_predicate(ship.mission):
            continue
        hull = hull_map.get(ship.hullid)
        has_scanner = apply_nebula_scanner and hull is not None and hull_has_nebula_scanner(hull)
        origins.append(
            CoverageOrigin(
                x=ship.x,
                y=ship.y,
                base_range=base_range,
                has_nebula_scanner=has_scanner,
            )
        )
    return origins


def ship_scan_origins(
    planets: Sequence[Planet],
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    ship_scan_range: float,
) -> list[CoverageOrigin]:
    """Planet and ship origins at ship-scan range (no separate starbase origins)."""
    origins: list[CoverageOrigin] = []
    for planet in planets:
        if planet.ownerid in owner_ids:
            origins.append(CoverageOrigin(x=planet.x, y=planet.y, base_range=ship_scan_range))
    origins.extend(
        _ship_origins(
            ships,
            hulls,
            owner_ids,
            base_range=ship_scan_range,
            apply_nebula_scanner=True,
        )
    )
    return origins


def active_sensor_sweep_origins(
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    sensor_mission_range: float,
) -> list[CoverageOrigin]:
    """Ships currently on Sensor Sweep / Bioscan (mission id 4)."""
    return _ship_origins(
        ships,
        hulls,
        owner_ids,
        base_range=sensor_mission_range,
        mission_predicate=is_sensor_sweep_or_bioscan_mission,
        apply_nebula_scanner=True,
    )


def potential_sensor_sweep_origins(
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    sensor_mission_range: float,
) -> list[CoverageOrigin]:
    """Ships that could Sensor Sweep, plus bioscan hulls (Bioscan instead).

    v1: every owned ship in scope is eligible (bioscan hulls use the same
    mission id; non-bioscan hulls could set Sensor Sweep).
    """
    return _ship_origins(
        ships,
        hulls,
        owner_ids,
        base_range=sensor_mission_range,
        apply_nebula_scanner=True,
    )


def active_minefield_detect_origins(
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    minefield_detect_range: float,
) -> list[CoverageOrigin]:
    """Ships currently on Mine Sweep (mission id 1)."""
    return _ship_origins(
        ships,
        hulls,
        owner_ids,
        base_range=minefield_detect_range,
        mission_predicate=is_mine_sweep_mission,
        apply_nebula_scanner=False,
    )


def potential_minefield_detect_origins(
    ships: Sequence[Ship],
    hulls: Sequence[Hull],
    owner_ids: frozenset[int],
    *,
    minefield_detect_range: float,
) -> list[CoverageOrigin]:
    """Ships that could set Mine Sweep (any starship per Nu help)."""
    return _ship_origins(
        ships,
        hulls,
        owner_ids,
        base_range=minefield_detect_range,
        apply_nebula_scanner=False,
    )


def build_visibility_overlays(
    turn: TurnInfo,
    *,
    fill_colors: Mapping[str, str] | None = None,
    fill_opacity: float = DEFAULT_FILL_OPACITY,
    sensor_mission_range: float = DEFAULT_SENSOR_MISSION_RANGE_LY,
    minefield_detect_range: float = DEFAULT_MINEFIELD_DETECT_RANGE_LY,
) -> list[MapRegionOverlay]:
    """Build hybrid overlays for all visibility region kinds (z-order order)."""
    colors = {**DEFAULT_KIND_FILL_COLORS, **(fill_colors or {})}
    owner_ids = visibility_owner_ids(turn.player.id, turn.relations)
    ship_scan_range = float(turn.settings.shipscanrange)
    nebulas: Sequence[Nebula] = turn.nebulas

    kind_origins: dict[str, list[CoverageOrigin]] = {
        KIND_SHIP_SCAN: ship_scan_origins(
            turn.planets,
            turn.ships,
            turn.hulls,
            owner_ids,
            ship_scan_range=ship_scan_range,
        ),
        KIND_POTENTIAL_SENSOR_SWEEP: potential_sensor_sweep_origins(
            turn.ships,
            turn.hulls,
            owner_ids,
            sensor_mission_range=sensor_mission_range,
        ),
        KIND_ACTIVE_SENSOR_SWEEP: active_sensor_sweep_origins(
            turn.ships,
            turn.hulls,
            owner_ids,
            sensor_mission_range=sensor_mission_range,
        ),
        KIND_POTENTIAL_MINEFIELD_DETECT: potential_minefield_detect_origins(
            turn.ships,
            turn.hulls,
            owner_ids,
            minefield_detect_range=minefield_detect_range,
        ),
        KIND_ACTIVE_MINEFIELD_DETECT: active_minefield_detect_origins(
            turn.ships,
            turn.hulls,
            owner_ids,
            minefield_detect_range=minefield_detect_range,
        ),
    }

    overlays: list[MapRegionOverlay] = []
    for kind in VISIBILITY_KIND_Z_ORDER:
        origins = kind_origins[kind]
        if not origins:
            continue
        # Minefield detect is not nebula-modulated (host / Nu help).
        coverage_nebulas: Sequence[Nebula] = () if kind in _DISK_ONLY_KINDS else nebulas
        coverage = build_hybrid_coverage(origins, coverage_nebulas)
        overlays.append(
            hybrid_coverage_to_overlay(
                coverage,
                kind=kind,
                overlay_id=f"visibility-{kind}",
                fill_color=colors[kind],
                fill_opacity=fill_opacity,
            )
        )
    return overlays
