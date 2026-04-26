"""Assemble connection route rows: direct and flare-assisted pairs (canonical public API)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.concepts.planet_connections._constants import _MAX_FLARE_CHAIN_DEPTH
from api.concepts.planet_connections.annuli import _build_flare_eligible_per_depth_center_annuli
from api.concepts.planet_connections.flare_pathfind import (
    _max_flare_arrival_extent,
    _pair_flare_path_either_direction,
)
from api.concepts.planet_connections.pairing import _canonical_pair_id
from api.concepts.planet_connections.spatial_index import _PlanetSpatialIndex
from api.concepts.planet_connections.wells import (
    _pair_has_direct_connection,
    max_travel_distance,
)
from api.concepts.warp_well import NORMAL_RADIUS
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics, timed_section
from api.models.planet import Planet


class FlareConnectionMode(StrEnum):
    """How flare-assisted routes are combined with direct warp-well reachability."""

    OFF = "off"
    INCLUDE = "include"
    ONLY = "only"


def _iter_flare_candidate_edges(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    *,
    max_travel: float,
    scan_flare: float,
    scan_direct: float,
    use_flare_discs: bool,
) -> Iterator[tuple[Planet, Planet, bool]]:
    """Each ``(A, B, in_flare_inner_disc)`` for ``A.id < B.id``; inner disc = center distance ≤
    ``max_travel`` (flare BFS is never run in that annulus, only the direct check)."""
    for planet_a in sorted_planets:
        ax, ay = float(planet_a.x), float(planet_a.y)
        if use_flare_discs:
            inner_ids: set[int] = {
                p.id
                for p in index.iter_planets_within_radius(
                    ax, ay, max_travel, min_planet_id_exclusive=planet_a.id
                )
            }
            candidates_outer = list(
                index.iter_planets_within_radius(
                    ax, ay, scan_flare, min_planet_id_exclusive=planet_a.id
                )
            )
        else:
            inner_ids = set()
            candidates_outer = list(
                index.iter_planets_within_radius(
                    ax, ay, scan_direct, min_planet_id_exclusive=planet_a.id
                )
            )
        for planet_b in candidates_outer:
            if planet_b.id <= planet_a.id:
                continue
            in_flare_inner = use_flare_discs and (planet_b.id in inner_ids)
            yield planet_a, planet_b, in_flare_inner


@dataclass
class ConnectionRoutesOutcome:
    """Result of :func:`connection_routes_with_options`."""

    routes: list[dict[str, bool | int | list | str | dict]]


def connection_routes_with_options(
    planets: list[Planet],
    *,
    warp_speed: int,
    gravitonic_movement: bool,
    flare_mode: FlareConnectionMode,
    flare_depth: int = 1,
    flare_bfs_use_distance_prune: bool = True,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    include_illustrative_routes: bool = False,
) -> ConnectionRoutesOutcome:
    """Canonical planet pairs (lower id -> higher id) with direct and/or flare connectivity.

    Flare eligibility uses per-*k* center-distance annuli
    ``(k*max_travel, k*hop_loose + NORMAL_RADIUS]`` (see
    :func:`_build_flare_eligible_per_depth_center_annuli`).

    **Candidates:** the spatial index is queried for inner disc and outer flare reach; expensive
    flare BFS runs only for annulus pairs. Set ``flare_bfs_use_distance_prune`` to False only
    for debugging.
    """
    if flare_depth < 1 or flare_depth > _MAX_FLARE_CHAIN_DEPTH:
        msg = f"flare_depth must be 1, 2, or 3, got {flare_depth}"
        raise ValueError(msg)
    max_travel = max_travel_distance(warp_speed, gravitonic_movement)
    movement = FlareMovementKind.GRAVITONIC if gravitonic_movement else FlareMovementKind.REGULAR
    use_flare_geometry = flare_mode is not FlareConnectionMode.OFF
    flares = flare_points_for_warp(warp_speed, movement) if use_flare_geometry else []

    scan_direct = max_travel + NORMAL_RADIUS
    scan_flare = scan_direct
    if use_flare_geometry and flares:
        extent = _max_flare_arrival_extent(flares)
        hop_loose = max(max_travel, extent)
        scan_flare = max(
            scan_flare,
            flare_depth * hop_loose + NORMAL_RADIUS,
        )

    index = _PlanetSpatialIndex(planets)
    sorted_planets = sorted(planets, key=lambda p: p.id)
    cr = diagnostics.child("connection_routes")
    hop_loose = max_travel
    if use_flare_geometry and flares:
        hop_loose = max(max_travel, _max_flare_arrival_extent(flares))

    def _build_flare_eligible(
        diag: Diagnostics,
    ) -> set[tuple[int, int]] | None:
        if not use_flare_geometry or not flares or flare_mode is FlareConnectionMode.OFF:
            return None
        fdiag = diag.child("flare_per_depth_center_union")
        fdiag.values["maxK"] = int(min(_MAX_FLARE_CHAIN_DEPTH, flare_depth))
        e1, e2, e3 = _build_flare_eligible_per_depth_center_annuli(
            sorted_planets,
            index,
            flares,
            max_travel,
            hop_loose,
            min(_MAX_FLARE_CHAIN_DEPTH, flare_depth),
            use_distance_prune=flare_bfs_use_distance_prune,
            diagnostics=fdiag,
        )
        s: set[tuple[int, int]] = set()
        if flare_depth >= 1:
            s |= e1
        if flare_depth >= 2:
            s |= e2
        if flare_depth >= 3:
            s |= e3
        return s

    use_flare_discs = use_flare_geometry and bool(flares)
    max_path_hops = min(_MAX_FLARE_CHAIN_DEPTH, flare_depth)

    def _append_flare_row(
        planet_a: Planet,
        planet_b: Planet,
        out: list[dict[str, object]],
        include_illustr: bool,
    ) -> None:
        row: dict[str, object] = {
            "fromPlanetId": planet_a.id,
            "toPlanetId": planet_b.id,
            "viaFlare": True,
        }
        if include_illustr:
            pth = _pair_flare_path_either_direction(
                planet_a,
                planet_b,
                flares,
                max_path_hops,
                index,
                max_travel,
                use_distance_prune=flare_bfs_use_distance_prune,
            )
            if pth is not None:
                row["illustrativeRoute"] = pth
        out.append(row)

    def _emit(
        out: list[dict[str, object]],
        u_flare: set[tuple[int, int]] | None,
        include_illustr: bool,
    ) -> None:
        for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=use_flare_discs,
        ):
            direct = _pair_has_direct_connection(planet_a, planet_b, max_travel)
            pair_key = _canonical_pair_id(planet_a, planet_b)
            exclusive_flare = (
                u_flare is not None and pair_key in u_flare and not in_flare_inner and not direct
            )
            if flare_mode == FlareConnectionMode.OFF:
                if direct:
                    out.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
            elif flare_mode == FlareConnectionMode.INCLUDE:
                if direct:
                    out.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
                elif exclusive_flare:
                    _append_flare_row(planet_a, planet_b, out, include_illustr)
            elif flare_mode == FlareConnectionMode.ONLY:
                if exclusive_flare:
                    _append_flare_row(planet_a, planet_b, out, include_illustr)
            else:
                msg = f"unsupported FlareConnectionMode: {flare_mode!r}"
                raise ValueError(msg)

    u_sel = _build_flare_eligible(cr)
    routes_out: list[dict[str, object]] = []
    ar = cr.child("assemble_routes")
    with timed_section(ar, "total"):
        _emit(routes_out, u_sel, include_illustrative_routes)
    ar.values["outRoutes"] = len(routes_out)
    routes_out.sort(key=lambda r: (int(r["fromPlanetId"]), int(r["toPlanetId"])))
    return ConnectionRoutesOutcome(routes=routes_out)


def connection_routes_for_planets(
    planets: list[Planet],
    *,
    warp_speed: int,
    gravitonic_movement: bool,
    flare_mode: FlareConnectionMode,
    flare_depth: int = 1,
    flare_bfs_use_distance_prune: bool = True,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
) -> list[dict[str, bool | int]]:
    """Same as :func:`connection_routes_with_options` without illustrative routes or diagnostics."""
    return connection_routes_with_options(
        planets,
        warp_speed=warp_speed,
        gravitonic_movement=gravitonic_movement,
        flare_mode=flare_mode,
        flare_depth=flare_depth,
        flare_bfs_use_distance_prune=flare_bfs_use_distance_prune,
        diagnostics=diagnostics,
    ).routes  # type: ignore[return-value]
