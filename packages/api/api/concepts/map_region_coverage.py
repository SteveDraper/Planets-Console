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
# When omitted, each origin uses default V(P) capping, with a Nebula Scanner
# floor when ``CoverageOrigin.has_nebula_scanner`` is set.
EffectiveRangeFn = Callable[[float, float], float]

# Inclusive map-cell AABB: (min_x, min_y, max_x, max_y).
CellAabb = tuple[int, int, int, int]

# Nebula Scanner ability: floor effective reach inside nebulae (still capped
# by base_range when base_range < 100).
NEBULA_SCANNER_FLOOR_LY = 100.0


@dataclass(frozen=True)
class CoverageOrigin:
    """Scan origin for hybrid coverage."""

    x: int
    y: int
    base_range: float
    has_nebula_scanner: bool = False


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
class MapRegionOverlayVertex:
    """Map-space point (ly) for a boundary path."""

    x: float
    y: float


@dataclass(frozen=True)
class MapRegionBoundaryLineEdge:
    """Straight segment between consecutive boundary vertices."""

    type: str = "line"


@dataclass(frozen=True)
class MapRegionBoundaryArcEdge:
    """Circular arc between consecutive boundary vertices (map-space clockwise)."""

    center_x: float
    center_y: float
    clockwise: bool
    type: str = "arc"


MapRegionBoundaryEdge = MapRegionBoundaryLineEdge | MapRegionBoundaryArcEdge


@dataclass(frozen=True)
class MapRegionCoverageGeometry:
    """Hybrid coverage footprint: ideal disks plus nebula-local patches."""

    disks: tuple[MapRegionOverlayDisk, ...]
    patches: tuple[MapRegionOverlayPatch, ...]
    type: str = "coverage"


@dataclass(frozen=True)
class MapRegionBoundaryGeometry:
    """Closed path boundary (line/arc edges) with optional envelope disks."""

    vertices: tuple[MapRegionOverlayVertex, ...]
    edges: tuple[MapRegionBoundaryEdge, ...]
    disks: tuple[MapRegionOverlayDisk, ...] = ()
    type: str = "boundary"


MapRegionOverlayGeometry = MapRegionCoverageGeometry | MapRegionBoundaryGeometry


@dataclass(frozen=True)
class MapRegionOverlay:
    """Analytic-agnostic shaded region overlay for the combined map.

    Geometry is discriminated: ``coverage`` (disks+patches) or ``boundary``
    (ordered vertices + line|arc edges, optional envelope disks). Optional
    annotations (``is_pinned``, ``status``, ``hover_summary``) are shared and
    ignored by analytics that do not use them.
    """

    kind: str
    id: str
    fill_color: str
    fill_opacity: float
    geometry: MapRegionOverlayGeometry
    is_pinned: bool | None = None
    status: str | None = None
    hover_summary: str | None = None


def default_effective_range(base_range: float, density: float) -> float:
    """Effective reach at a cell: ``min(base_range, V(P))`` when density > 0."""
    if density <= 0:
        return base_range
    visibility = nebula_visibility_ly(density)
    if visibility is None:
        return base_range
    return min(base_range, float(visibility))


def nebula_scanner_effective_range(base_range: float, density: float) -> float:
    """Nebula Scanner reach: ``max(min(base, V(P)), min(base, 100))`` in density.

    Outside density the ideal ``base_range`` applies. The 100 ly floor only
    raises reach where density would cut deeper; if ``base_range < 100``, the
    floor is capped by ``base_range``.
    """
    if density <= 0:
        return base_range
    capped = default_effective_range(base_range, density)
    return max(capped, min(base_range, NEBULA_SCANNER_FLOOR_LY))


def _origin_effective_range(
    origin: CoverageOrigin,
    density: float,
    *,
    effective_range: EffectiveRangeFn | None,
) -> float:
    if effective_range is not None:
        return effective_range(origin.base_range, density)
    if origin.has_nebula_scanner:
        return nebula_scanner_effective_range(origin.base_range, density)
    return default_effective_range(origin.base_range, density)


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


def _merge_until_disjoint(boxes: Sequence[CellAabb]) -> list[CellAabb]:
    """Merge AABBs until no two results overlap.

    Needed because AABB-union of an overlap connected component can still
    contain a disjoint box that sits in a pocket of the union rectangle.
    """
    out = list(boxes)
    changed = True
    while changed:
        changed = False
        next_out: list[CellAabb] = []
        for box in out:
            for i, existing in enumerate(next_out):
                if _aabbs_overlap(box, existing):
                    next_out[i] = _aabb_union(existing, box)
                    changed = True
                    break
            else:
                next_out.append(box)
        out = next_out
    return out


def _merged_patch_aabbs(
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> list[CellAabb]:
    """Union nebula AABBs that touch at least one coverage disk.

    Returns a non-overlapping partition of covering AABBs (merge until disjoint).
    """
    boxes: list[CellAabb] = []
    for nebula in nebulas:
        if not any(_disk_intersects_nebula(o, nebula) for o in origins):
            continue
        boxes.append(_nebula_aabb(nebula))
    if not boxes:
        return []
    return _merge_until_disjoint(boxes)


def _cell_covered(
    x: int,
    y: int,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn | None,
) -> bool:
    density = nebula_density_at(nebulas, x, y)
    for origin in origins:
        if origin.base_range <= 0:
            continue
        if density <= 0:
            reach = origin.base_range
        else:
            reach = _origin_effective_range(origin, density, effective_range=effective_range)
        if distance_ly(origin.x, origin.y, x, y) <= reach:
            return True
    return False


def point_covered_by_origins(
    x: float,
    y: float,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn | None = None,
) -> bool:
    """True when map point ``(x, y)`` is inside any origin's effective reach.

    Coordinates are rounded to integer map cells (same grid as hybrid patches).
    """
    return _cell_covered(
        int(round(x)),
        int(round(y)),
        origins,
        nebulas,
        effective_range=effective_range,
    )


def _build_patch_for_aabb(
    aabb: CellAabb,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    *,
    effective_range: EffectiveRangeFn | None,
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
    disk-intersecting nebulas (merge until no two patch AABBs overlap). Inside
    a patch AABB, coverage truth includes ideal reach outside density and
    V(P)-modulated reach where density > 0.
    """
    active_origins = [o for o in origins if o.base_range > 0]
    disks = tuple(MapRegionOverlayDisk(x=o.x, y=o.y, radius=o.base_range) for o in active_origins)
    if not active_origins:
        return HybridCoverage(disks=(), patches=())

    patches: list[MapRegionOverlayPatch] = []
    for aabb in _merged_patch_aabbs(active_origins, nebulas):
        patch = _build_patch_for_aabb(
            aabb,
            active_origins,
            nebulas,
            effective_range=effective_range,
        )
        if patch is not None:
            patches.append(patch)

    return HybridCoverage(disks=disks, patches=tuple(patches))


def _disks_to_wire(disks: tuple[MapRegionOverlayDisk, ...]) -> list[dict]:
    return [{"x": d.x, "y": d.y, "radius": d.radius} for d in disks]


def _patches_to_wire(patches: tuple[MapRegionOverlayPatch, ...]) -> list[dict]:
    return [
        {
            "originX": p.origin_x,
            "originY": p.origin_y,
            "width": p.width,
            "height": p.height,
            "coverageRle": [
                {"length": run.length, "covered": run.covered} for run in p.coverage_rle
            ],
        }
        for p in patches
    ]


def _boundary_edge_to_wire(edge: MapRegionBoundaryEdge) -> dict:
    if isinstance(edge, MapRegionBoundaryLineEdge):
        return {"type": "line"}
    return {
        "type": "arc",
        "centerX": edge.center_x,
        "centerY": edge.center_y,
        "clockwise": edge.clockwise,
    }


def _geometry_to_wire(geometry: MapRegionOverlayGeometry) -> dict:
    if isinstance(geometry, MapRegionCoverageGeometry):
        return {
            "type": "coverage",
            "disks": _disks_to_wire(geometry.disks),
            "patches": _patches_to_wire(geometry.patches),
        }
    payload: dict = {
        "type": "boundary",
        "vertices": [{"x": v.x, "y": v.y} for v in geometry.vertices],
        "edges": [_boundary_edge_to_wire(e) for e in geometry.edges],
    }
    if geometry.disks:
        payload["disks"] = _disks_to_wire(geometry.disks)
    return payload


def map_region_overlay_to_wire(overlay: MapRegionOverlay) -> dict:
    """Serialize a map region overlay to camelCase JSON for map payloads."""
    wire: dict = {
        "kind": overlay.kind,
        "id": overlay.id,
        "fillColor": overlay.fill_color,
        "fillOpacity": overlay.fill_opacity,
        "geometry": _geometry_to_wire(overlay.geometry),
    }
    if overlay.is_pinned is not None:
        wire["isPinned"] = overlay.is_pinned
    if overlay.status is not None:
        wire["status"] = overlay.status
    if overlay.hover_summary is not None:
        wire["hoverSummary"] = overlay.hover_summary
    return wire


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
        geometry=MapRegionCoverageGeometry(
            disks=coverage.disks,
            patches=coverage.patches,
        ),
    )


def boundary_to_overlay(
    *,
    kind: str,
    overlay_id: str,
    fill_color: str,
    fill_opacity: float,
    vertices: Sequence[MapRegionOverlayVertex],
    edges: Sequence[MapRegionBoundaryEdge],
    disks: Sequence[MapRegionOverlayDisk] = (),
    is_pinned: bool | None = None,
    status: str | None = None,
    hover_summary: str | None = None,
) -> MapRegionOverlay:
    """Wrap a closed boundary path (and optional envelope disks) for the wire.

    ``len(edges)`` must equal ``len(vertices)``: edge ``i`` connects vertex
    ``i`` to vertex ``(i + 1) % n`` (closed ring).
    """
    verts = tuple(vertices)
    edge_tuple = tuple(edges)
    if len(verts) < 3:
        raise ValueError("boundary requires at least 3 vertices")
    if len(edge_tuple) != len(verts):
        raise ValueError(
            f"boundary edge count {len(edge_tuple)} must equal vertex count {len(verts)}"
        )
    return MapRegionOverlay(
        kind=kind,
        id=overlay_id,
        fill_color=fill_color,
        fill_opacity=fill_opacity,
        geometry=MapRegionBoundaryGeometry(
            vertices=verts,
            edges=edge_tuple,
            disks=tuple(disks),
        ),
        is_pinned=is_pinned,
        status=status,
        hover_summary=hover_summary,
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
