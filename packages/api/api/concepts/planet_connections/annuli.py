"""Per-depth center annuli for exclusive flare eligibility (normal vs flare pairs)."""

from __future__ import annotations

import math

from api.concepts.planet_connections._diagnostics import (
    _FlareBfsHotspotTimings,
    _FlareBfsMetrics,
    _LatticeBuildDiagnostics,
)
from api.concepts.planet_connections.flare_pathfind import (
    _pair_reachable_via_flare_either_direction,
)
from api.concepts.planet_connections.pairing import _canonical_pair_id
from api.concepts.planet_connections.spatial_index import _PlanetSpatialIndex
from api.concepts.planet_connections.wells import _pair_reachable_in_k_normal_moves
from api.concepts.warp_well import NORMAL_RADIUS
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics, timed_section
from api.models.flare_point import FlarePoint
from api.models.planet import Planet


def _per_depth_center_annulus_radii(
    k: int, max_travel: float, hop_loose: float
) -> tuple[float, float]:
    """Center-distance annulus (exclusive inner, inclusive outer) for per-depth *k*."""
    inner = k * max_travel
    outer = k * hop_loose + float(NORMAL_RADIUS)
    return (inner, outer)


def _list_per_depth_center_annulus_for_k(
    sorted_planets: list[Planet],
    *,
    k: int,
    max_travel: float,
    hop_loose: float,
) -> list[tuple[Planet, Planet]]:
    inner, outer = _per_depth_center_annulus_radii(k, max_travel, hop_loose)
    if outer <= inner + 1e-12:
        return []
    out: list[tuple[Planet, Planet]] = []
    for i, pa in enumerate(sorted_planets):
        ax, ay = float(pa.x), float(pa.y)
        for pb in sorted_planets[i + 1 :]:
            bx, by = float(pb.x), float(pb.y)
            d = math.hypot(bx - ax, by - ay)
            if inner < d <= outer + 1e-9:
                out.append((pa, pb))
    return out


def _build_flare_eligible_per_depth_center_annuli(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    flares: list[FlarePoint],
    max_travel: float,
    hop_loose: float,
    max_k: int,
    *,
    use_distance_prune: bool,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]], set[tuple[int, int]]]:
    e1: set[tuple[int, int]] = set()
    e2: set[tuple[int, int]] = set()
    e3: set[tuple[int, int]] = set()
    lattice_diagnostics = _LatticeBuildDiagnostics() if diagnostics.enabled else None
    m1 = _FlareBfsMetrics() if diagnostics.enabled else None
    m2 = _FlareBfsMetrics() if diagnostics.enabled else None
    m3 = _FlareBfsMetrics() if diagnostics.enabled else None
    hot1 = _FlareBfsHotspotTimings() if diagnostics.enabled else None
    hot2 = _FlareBfsHotspotTimings() if diagnostics.enabled else None
    hot3 = _FlareBfsHotspotTimings() if diagnostics.enabled else None
    diagnostics.values["maxTravel"] = max_travel
    diagnostics.values["hopLoose"] = hop_loose
    diagnostics.values["normalRadius"] = float(NORMAL_RADIUS)
    for kk in range(1, max_k + 1):
        inn, outv = _per_depth_center_annulus_radii(kk, max_travel, hop_loose)
        diagnostics.values[f"annulusK{kk}Inner"] = inn
        diagnostics.values[f"annulusK{kk}Outer"] = outv
    if max_k >= 1:
        ann1 = _list_per_depth_center_annulus_for_k(
            sorted_planets, k=1, max_travel=max_travel, hop_loose=hop_loose
        )
        inner1, outer1 = _per_depth_center_annulus_radii(1, max_travel, hop_loose)
        d1 = diagnostics.child("flare_per_depth_center_k1")
        d1.values["k"] = 1
        d1.values["annulusInnerRadius"] = inner1
        d1.values["annulusOuterRadius"] = outer1
        d1.values["annulusPairs"] = len(ann1)
        if diagnostics.enabled and m1 is not None:
            with timed_section(d1, "total"):
                for planet_a, planet_b in ann1:
                    key = _canonical_pair_id(planet_a, planet_b)
                    if not _pair_reachable_in_k_normal_moves(
                        planet_a, planet_b, max_travel, 1
                    ) and _pair_reachable_via_flare_either_direction(
                        planet_a,
                        planet_b,
                        flares,
                        1,
                        index,
                        max_travel,
                        use_distance_prune=use_distance_prune,
                        bfs_metrics=m1,
                        hotspot_timings=hot1,
                        lattice_diagnostics=lattice_diagnostics,
                    ):
                        e1.add(key)
            d1.values["pairsTestedInLayer"] = len(ann1)
            d1.values["connectionsFoundInLayer"] = len(e1)
            d1.values["cumulativeConnections"] = len(e1)
            d1.values["bfsRuns"] = m1.bfs_runs
            d1.values["intermediateRoutePoints"] = m1.bfs_dequeues
            d1.values["searchEnqueues"] = m1.bfs_enqueues
            if hot1 is not None:
                hot1.add_to_diagnostics(d1)
        else:
            for planet_a, planet_b in ann1:
                key = _canonical_pair_id(planet_a, planet_b)
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 1
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    1,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=None,
                ):
                    e1.add(key)
    if max_k < 2:
        if diagnostics.enabled and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)
    if max_k >= 2:
        ann2 = _list_per_depth_center_annulus_for_k(
            sorted_planets, k=2, max_travel=max_travel, hop_loose=hop_loose
        )
        inner2, outer2 = _per_depth_center_annulus_radii(2, max_travel, hop_loose)
        d2 = diagnostics.child("flare_per_depth_center_k2")
        d2.values["k"] = 2
        d2.values["annulusInnerRadius"] = inner2
        d2.values["annulusOuterRadius"] = outer2
        d2.values["annulusPairs"] = len(ann2)
        if diagnostics.enabled and m2 is not None:
            with timed_section(d2, "total"):
                n_past_s1 = 0
                for planet_a, planet_b in ann2:
                    key = _canonical_pair_id(planet_a, planet_b)
                    if key in e1:
                        continue
                    n_past_s1 += 1
                    if not _pair_reachable_in_k_normal_moves(
                        planet_a, planet_b, max_travel, 2
                    ) and _pair_reachable_via_flare_either_direction(
                        planet_a,
                        planet_b,
                        flares,
                        2,
                        index,
                        max_travel,
                        use_distance_prune=use_distance_prune,
                        bfs_metrics=m2,
                        hotspot_timings=hot2,
                        lattice_diagnostics=lattice_diagnostics,
                    ):
                        e2.add(key)
            d2.values["pairsTestedInLayer"] = len(ann2)
            d2.values["pairCandidatesPastShallowerLayers"] = n_past_s1
            d2.values["connectionsFoundInLayer"] = len(e2)
            d2.values["cumulativeConnections"] = len(e1) + len(e2)
            d2.values["bfsRuns"] = m2.bfs_runs
            d2.values["intermediateRoutePoints"] = m2.bfs_dequeues
            d2.values["searchEnqueues"] = m2.bfs_enqueues
            if hot2 is not None:
                hot2.add_to_diagnostics(d2)
        else:
            for planet_a, planet_b in ann2:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e1:
                    continue
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 2
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    2,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=None,
                ):
                    e2.add(key)
    if max_k < 3:
        if diagnostics.enabled and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)
    ann3 = _list_per_depth_center_annulus_for_k(
        sorted_planets, k=3, max_travel=max_travel, hop_loose=hop_loose
    )
    inner3, outer3 = _per_depth_center_annulus_radii(3, max_travel, hop_loose)
    e12 = e1 | e2
    d3 = diagnostics.child("flare_per_depth_center_k3")
    d3.values["k"] = 3
    d3.values["annulusInnerRadius"] = inner3
    d3.values["annulusOuterRadius"] = outer3
    d3.values["annulusPairs"] = len(ann3)
    if diagnostics.enabled and m3 is not None:
        with timed_section(d3, "total"):
            n_past_s12 = 0
            for planet_a, planet_b in ann3:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e12:
                    continue
                n_past_s12 += 1
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 3
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    3,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m3,
                    hotspot_timings=hot3,
                    lattice_diagnostics=lattice_diagnostics,
                ):
                    e3.add(key)
        d3.values["pairsTestedInLayer"] = len(ann3)
        d3.values["pairCandidatesPastShallowerLayers"] = n_past_s12
        d3.values["connectionsFoundInLayer"] = len(e3)
        d3.values["cumulativeConnections"] = len(e1) + len(e2) + len(e3)
        d3.values["bfsRuns"] = m3.bfs_runs
        d3.values["intermediateRoutePoints"] = m3.bfs_dequeues
        d3.values["searchEnqueues"] = m3.bfs_enqueues
        if hot3 is not None:
            hot3.add_to_diagnostics(d3)
    else:
        for planet_a, planet_b in ann3:
            key = _canonical_pair_id(planet_a, planet_b)
            if key in e12:
                continue
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 3
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                3,
                index,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e3.add(key)
    if diagnostics.enabled and lattice_diagnostics is not None:
        lattice_diagnostics.add_to_diagnostics(diagnostics)
    return (e1, e2, e3)
