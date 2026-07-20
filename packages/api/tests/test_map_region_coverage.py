"""Tests for hybrid map-region coverage (disks + nebula-local patches)."""

from api.concepts.map_region_coverage import (
    CoverageOrigin,
    build_hybrid_coverage,
    decode_patch_coverage,
    hybrid_coverage_to_overlay,
    map_region_overlay_to_wire,
    patch_cell_covered,
)
from api.concepts.stellar_cartography.nebula_visibility import nebula_visibility_ly
from api.models.space import Nebula


def test_empty_origins_yield_empty_coverage():
    coverage = build_hybrid_coverage(
        [],
        [Nebula(id=1, x=0, y=0, radius=50, intensity=40)],
    )
    assert coverage.disks == ()
    assert coverage.patches == ()


def test_disk_only_no_nebulas():
    coverage = build_hybrid_coverage(
        [
            CoverageOrigin(x=100, y=200, base_range=150),
            CoverageOrigin(x=300, y=200, base_range=80),
        ],
        [],
    )
    assert len(coverage.disks) == 2
    assert coverage.disks[0].x == 100
    assert coverage.disks[0].y == 200
    assert coverage.disks[0].radius == 150
    assert coverage.disks[1].radius == 80
    assert coverage.patches == ()


def test_zero_base_range_origins_omitted():
    coverage = build_hybrid_coverage(
        [CoverageOrigin(x=0, y=0, base_range=0)],
        [Nebula(id=1, x=0, y=0, radius=10, intensity=40)],
    )
    assert coverage.disks == ()
    assert coverage.patches == ()


def test_nebula_far_from_disk_emits_no_patch():
    coverage = build_hybrid_coverage(
        [CoverageOrigin(x=0, y=0, base_range=50)],
        [Nebula(id=1, x=1000, y=1000, radius=20, intensity=40)],
    )
    assert len(coverage.disks) == 1
    assert coverage.patches == ()


def test_nebula_dented_coverage_patch_is_local():
    # Dense nebula: V(P) at center is well below base_range, so the ideal disk
    # is dented inside the nebula AABB.
    origin = CoverageOrigin(x=0, y=0, base_range=200)
    nebula = Nebula(id=1, x=100, y=0, name="Fog", radius=40, intensity=72)
    coverage = build_hybrid_coverage([origin], [nebula])

    assert len(coverage.disks) == 1
    assert len(coverage.patches) == 1
    patch = coverage.patches[0]
    assert patch.origin_x == 60
    assert patch.origin_y == -40
    assert patch.width == 81
    assert patch.height == 81

    density_at_center = 72.0  # ceil(72 * 1.0) at center
    visibility = nebula_visibility_ly(density_at_center)
    assert visibility is not None
    assert visibility < 200

    # Center of nebula: dist from origin is 100; covered iff 100 <= V(P).
    center_covered = patch_cell_covered(patch, 100, 0)
    assert center_covered == (100 <= visibility)

    # Cell outside nebula radius but inside AABB corner: density 0, ideal reach.
    corner = patch_cell_covered(patch, 60, -40)
    assert corner is not None
    # Dist from (0,0) to (60,-40) = hypot(60,40)=72.11 < 200 → covered
    assert corner is True

    cells = decode_patch_coverage(patch)
    assert len(cells) == patch.width * patch.height
    assert sum(1 for c in cells if c) < len(cells)


def test_wire_round_trip_shape():
    coverage = build_hybrid_coverage(
        [CoverageOrigin(x=10, y=20, base_range=50)],
        [Nebula(id=1, x=30, y=20, radius=15, intensity=39)],
    )
    overlay = hybrid_coverage_to_overlay(
        coverage,
        kind="demo",
        overlay_id="demo-1",
        fill_color="#22c55e",
        fill_opacity=0.25,
    )
    wire = map_region_overlay_to_wire(overlay)
    assert wire["kind"] == "demo"
    assert wire["id"] == "demo-1"
    assert wire["fillColor"] == "#22c55e"
    assert wire["fillOpacity"] == 0.25
    assert wire["disks"] == [{"x": 10, "y": 20, "radius": 50}]
    assert len(wire["patches"]) == 1
    patch = wire["patches"][0]
    assert patch["originX"] == 15
    assert patch["width"] == 31
    assert patch["height"] == 31
    assert isinstance(patch["coverageRle"], list)
    assert patch["coverageRle"][0].keys() >= {"length", "covered"}


def _patch_aabb(patch) -> tuple[int, int, int, int]:
    return (
        patch.origin_x,
        patch.origin_y,
        patch.origin_x + patch.width - 1,
        patch.origin_y + patch.height - 1,
    )


def _aabbs_overlap(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def test_overlapping_nebulas_merge_into_one_non_overlapping_patch():
    origin = CoverageOrigin(x=0, y=0, base_range=200)
    n1 = Nebula(id=1, x=50, y=0, name="A", radius=40, intensity=40)
    n2 = Nebula(id=2, x=70, y=0, name="B", radius=40, intensity=40)
    coverage = build_hybrid_coverage([origin], [n1, n2])

    assert len(coverage.disks) == 1
    assert len(coverage.patches) == 1
    patch = coverage.patches[0]
    # Union of [10,-40]..[90,40] and [30,-40]..[110,40]
    assert patch.origin_x == 10
    assert patch.origin_y == -40
    assert patch.width == 101
    assert patch.height == 81
    # Overlap cell is owned by exactly one patch (the merged AABB).
    assert patch_cell_covered(patch, 60, 0) is not None


def test_disjoint_nebulas_emit_non_overlapping_patches():
    origin = CoverageOrigin(x=0, y=0, base_range=500)
    n1 = Nebula(id=1, x=100, y=0, name="West", radius=20, intensity=40)
    n2 = Nebula(id=2, x=400, y=0, name="East", radius=20, intensity=40)
    coverage = build_hybrid_coverage([origin], [n1, n2])

    assert len(coverage.patches) == 2
    a, b = coverage.patches
    assert not _aabbs_overlap(_patch_aabb(a), _patch_aabb(b))
    assert patch_cell_covered(a, 100, 0) is not None
    assert patch_cell_covered(b, 100, 0) is None
    assert patch_cell_covered(b, 400, 0) is not None
    assert patch_cell_covered(a, 400, 0) is None
