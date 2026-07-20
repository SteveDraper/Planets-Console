"""Hybrid map-region coverage: ideal disks plus nebula-local patches.

Core owns coverage truth. The SPA blits disks and patches; it does not
reimplement V(P) modulation. Patch AABBs are a non-overlapping partition and
exclusive blit authority (clip disks against them, then paint each patch once).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from api.concepts.stellar_cartography.nebula_visibility import (
    NebulaCenter,
    distance_ly,
    nebula_density_at,
    nebula_visibility_ly,
)

# Optional hook: (base_range, density) -> effective range at a modulated cell.
# Default applies min(base_range, V(P)). Nebula Scanner and similar land later.
EffectiveRangeFn = Callable[[float, float], float]

# Inclusive map-cell AABB: (min_x, min_y, max_x, max_y).
CellAabb = tuple[int, int, int, int]


@dataclass(frozen=True)
class CoverageOrigin:
    """Scan origin for hybrid coverage."""

    x: int
    y: int
    base_range: float


@dataclass(frozen=True)
class MapRegionOverlayDisk:
    """Ideal coverage disk in game ly."""

    x: int
    y: int
    radius: float


@dataclass(frozen=True)
class CoverageRleRun:
    """One run-length segment of a patch coverage mask."""

    length: int
    covered: bool


@dataclass(frozen=True)
class MapRegionOverlayPatch:
    """Nebula-local coverage patch (1 ly cells, row-major RLE)."""

    origin_x: int
    origin_y: int
    width: int
    height: int
    coverage_rle: tuple[CoverageRleRun, ...]


@dataclass(frozen=True)
class HybridCoverage:
    """Disk union where unmodulated, plus patches where nebulae distort."""

    disks: tuple[MapRegionOverlayDisk, ...]
    patches: tuple[MapRegionOverlayPatch, ...]


@dataclass(frozen=True)
class MapRegionOverlay:
    """Analytic-agnostic shaded region overlay for the combined map."""

    kind: str
    id: str
    fill_color: str
    fill_opacity: float
    disks: tuple[MapRegionOverlayDisk, ...]
    patches: tuple[MapRegionOverlayPatch, ...]


def default_effective_range(base_range: float, density: float) -> float:
    """Effective reach at a cell: ``min(base_range, V(P))`` when density > 0."""
    if density <= 0:
        return base_range
    visibility = nebula_visibility_ly(density)
    if visibility is None:
        return base_range
    return min(base_range, float(visibility))


def _encode_coverage_rle(cells: Sequence[bool]) -> tuple[CoverageRleRun, ...]:
    if not cells:
        return ()
    runs: list[CoverageRleRun] = []
    current = cells[0]
    length = 1
    for covered in cells[1:]:
        if covered == current:
            length += 1
            continue
        runs.append(CoverageRleRun(length=length, covered=current))
        current = covered
        length = 1
    runs.append(CoverageRleRun(length=length, covered=current))
    return tuple(runs)


def _disk_intersects_nebula(origin: CoverageOrigin, nebula: NebulaCenter) -> bool:
    if nebula.radius <= 0 or nebula.id < 0 or origin.base_range <= 0:
        return False
    return distance_ly(origin.x, origin.y, nebula.x, nebula.y) <= (
        origin.base_range + nebula.radius
    )


def _nebula_aabb(nebula: NebulaCenter) -> CellAabb:
    """Inclusive AABB of the nebula disk as integer map cells."""
    r = nebula.radius
    return (
        nebula.x - r,
        nebula.y - r,
        nebula.x + r,
        nebula.y + r,
    )


def _aabbs_overlap(a: CellAabb, b: CellAabb) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _aabb_union(a: CellAabb, b: CellAabb) -> CellAabb:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merged_patch_aabbs(
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> list[CellAabb]:
    """Union intersecting nebula AABBs that touch at least one coverage disk.

    Returns a non-overlapping partition (connected components of AABB overlap).
    """
    boxes: list[CellAabb] = []
    for nebula in nebulas:
        if not any(_disk_intersects_nebula(o, nebula) for o in origins):
            continue
        boxes.append(_nebula_aabb(nebula))
    if not boxes:
        return []

    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _aabbs_overlap(boxes[i], boxes[j]):
                union(i, j)

    merged: dict[int, CellAabb] = {}
    for i, box in enumerate(boxes):
        root = find(i)
        existing = merged.get(root)
        merged[root] = box if existing is None else _aabb_union(existing, box)
    return list(merged.values())


def _cell_covered(
    x: int,
    y: int,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn,
) -> bool:
    density = nebula_density_at(nebulas, x, y)
    for origin in origins:
        if origin.base_range <= 0:
            continue
        reach = effective_range(origin.base_range, density) if density > 0 else origin.base_range
        if distance_ly(origin.x, origin.y, x, y) <= reach:
            return True
    return False


def _build_patch_for_aabb(
    aabb: CellAabb,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn,
) -> MapRegionOverlayPatch | None:
    min_x, min_y, max_x, max_y = aabb
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    if width <= 0 or height <= 0:
        return None

    cells: list[bool] = []
    for row in range(height):
        y = min_y + row
        for col in range(width):
            x = min_x + col
            cells.append(
                _cell_covered(
                    x,
                    y,
                    origins,
                    nebulas,
                    effective_range=effective_range,
                )
            )
    return MapRegionOverlayPatch(
        origin_x=min_x,
        origin_y=min_y,
        width=width,
        height=height,
        coverage_rle=_encode_coverage_rle(cells),
    )


def build_hybrid_coverage(
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn | None = None,
) -> HybridCoverage:
    """Build ideal disks plus nebula-local patches for the given origins.

    Disks are one per origin at ``base_range``. Patches cover merged AABBs of
    disk-intersecting nebulas (connected components of AABB overlap) so patch
    regions never overlap. Inside a patch AABB, coverage truth includes ideal
    reach outside density and V(P)-modulated reach where density > 0.
    """
    active_origins = [o for o in origins if o.base_range > 0]
    disks = tuple(MapRegionOverlayDisk(x=o.x, y=o.y, radius=o.base_range) for o in active_origins)
    if not active_origins:
        return HybridCoverage(disks=(), patches=())

    modulation = effective_range or default_effective_range
    patches: list[MapRegionOverlayPatch] = []
    for aabb in _merged_patch_aabbs(active_origins, nebulas):
        patch = _build_patch_for_aabb(
            aabb,
            active_origins,
            nebulas,
            effective_range=modulation,
        )
        if patch is not None:
            patches.append(patch)

    return HybridCoverage(disks=disks, patches=tuple(patches))


def map_region_overlay_to_wire(overlay: MapRegionOverlay) -> dict:
    """Serialize a map region overlay to camelCase JSON for map payloads."""
    return {
        "kind": overlay.kind,
        "id": overlay.id,
        "fillColor": overlay.fill_color,
        "fillOpacity": overlay.fill_opacity,
        "disks": [{"x": d.x, "y": d.y, "radius": d.radius} for d in overlay.disks],
        "patches": [
            {
                "originX": p.origin_x,
                "originY": p.origin_y,
                "width": p.width,
                "height": p.height,
                "coverageRle": [
                    {"length": run.length, "covered": run.covered} for run in p.coverage_rle
                ],
            }
            for p in overlay.patches
        ],
    }


def hybrid_coverage_to_overlay(
    coverage: HybridCoverage,
    *,
    kind: str,
    overlay_id: str,
    fill_color: str,
    fill_opacity: float,
) -> MapRegionOverlay:
    """Wrap hybrid geometry with style metadata for the wire."""
    return MapRegionOverlay(
        kind=kind,
        id=overlay_id,
        fill_color=fill_color,
        fill_opacity=fill_opacity,
        disks=coverage.disks,
        patches=coverage.patches,
    )


def decode_patch_coverage(patch: MapRegionOverlayPatch) -> list[bool]:
    """Expand RLE to a flat row-major boolean mask (tests / tooling)."""
    expected = patch.width * patch.height
    cells: list[bool] = []
    for run in patch.coverage_rle:
        if run.length < 0:
            raise ValueError(f"negative RLE length: {run.length}")
        cells.extend([run.covered] * run.length)
    if len(cells) != expected:
        raise ValueError(f"RLE length {len(cells)} does not match patch size {expected}")
    return cells


def patch_cell_covered(patch: MapRegionOverlayPatch, x: int, y: int) -> bool | None:
    """Return coverage at ``(x, y)`` if inside the patch AABB, else ``None``."""
    if x < patch.origin_x or y < patch.origin_y:
        return None
    col = x - patch.origin_x
    row = y - patch.origin_y
    if col >= patch.width or row >= patch.height:
        return None
    cells = decode_patch_coverage(patch)
    return cells[row * patch.width + col]
