"""Tests for hybrid map-region coverage (disks + nebula-local patches)."""

import math

from api.concepts.map_region_coverage import (
    CoverageOrigin,
    MapRegionBoundaryArcEdge,
    MapRegionBoundaryLineEdge,
    MapRegionOverlayDisk,
    MapRegionOverlayVertex,
    MapRegionPossibleOwner,
    boundary_to_overlay,
    build_hybrid_coverage,
    decode_patch_coverage,
    hybrid_coverage_to_overlay,
    iter_annulus_polar_sample_points,
    map_region_overlay_to_wire,
    patch_cell_covered,
    point_covered_by_origins,
)
from api.concepts.stellar_cartography.nebula_visibility import nebula_visibility_ly
from api.models.space import Nebula


def test_iter_annulus_polar_sample_points_full_circle_omits_seam():
    points = list(
        iter_annulus_polar_sample_points(
            center=(0.0, 0.0),
            angle_start=0.0,
            angle_end=2.0 * math.pi,
            r_inner=0.0,
            r_outer=10.0,
            closed_angle=False,
        )
    )
    closed = list(
        iter_annulus_polar_sample_points(
            center=(0.0, 0.0),
            angle_start=0.0,
            angle_end=2.0 * math.pi,
            r_inner=0.0,
            r_outer=10.0,
            closed_angle=True,
        )
    )
    assert points
    assert len(closed) > len(points)


def test_iter_annulus_polar_sample_points_excludes_inner_boundary():
    points = list(
        iter_annulus_polar_sample_points(
            center=(0.0, 0.0),
            angle_start=0.0,
            angle_end=math.pi / 2.0,
            r_inner=10.0,
            r_outer=20.0,
            closed_angle=True,
            exclude_inner_boundary=True,
        )
    )
    assert points
    assert all((x * x + y * y) ** 0.5 > 10.0 - 1e-6 for x, y in points)


def test_point_covered_by_origins_matches_disk():
    origins = [CoverageOrigin(x=0, y=0, base_range=100)]
    assert point_covered_by_origins(50, 0, origins, []) is True
    assert point_covered_by_origins(150, 0, origins, []) is False


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
    assert wire["geometry"]["type"] == "coverage"
    assert wire["geometry"]["disks"] == [{"x": 10, "y": 20, "radius": 50}]
    assert len(wire["geometry"]["patches"]) == 1
    patch = wire["geometry"]["patches"][0]
    assert patch["originX"] == 15
    assert patch["width"] == 31
    assert patch["height"] == 31
    assert isinstance(patch["coverageRle"], list)
    assert patch["coverageRle"][0].keys() >= {"length", "covered"}
    assert "isPinned" not in wire
    assert "status" not in wire
    assert "candidateCount" not in wire
    assert "playerLabel" not in wire
    assert "hoverSummary" not in wire


def test_boundary_wire_round_trip_with_annotations():
    overlay = boundary_to_overlay(
        kind="homeworld-sector",
        overlay_id="sector-0",
        fill_color="#f97316",
        fill_opacity=0.2,
        vertices=(
            MapRegionOverlayVertex(x=200.0, y=0.0),
            MapRegionOverlayVertex(x=0.0, y=200.0),
            MapRegionOverlayVertex(x=0.0, y=100.0),
            MapRegionOverlayVertex(x=100.0, y=0.0),
        ),
        edges=(
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=False),
            MapRegionBoundaryLineEdge(),
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=True),
            MapRegionBoundaryLineEdge(),
        ),
        disks=(MapRegionOverlayDisk(x=150, y=50, radius=81),),
        is_pinned=True,
        status="ok",
        candidate_count=1,
        player_label="koshling (The Lizard Alliance)",
    )
    wire = map_region_overlay_to_wire(overlay)
    assert wire["geometry"]["type"] == "boundary"
    assert len(wire["geometry"]["vertices"]) == 4
    assert wire["geometry"]["edges"][0] == {
        "type": "arc",
        "centerX": 0.0,
        "centerY": 0.0,
        "clockwise": False,
    }
    assert wire["geometry"]["edges"][1] == {"type": "line"}
    assert wire["geometry"]["disks"] == [{"x": 150, "y": 50, "radius": 81}]
    assert wire["isPinned"] is True
    assert wire["status"] == "ok"
    assert wire["candidateCount"] == 1
    assert wire["playerLabel"] == "koshling (The Lizard Alliance)"
    assert "hoverSummary" not in wire


def test_disks_only_boundary_wire():
    from api.concepts.map_region_coverage import disks_to_boundary_overlay

    overlay = disks_to_boundary_overlay(
        kind="homeworld-planet-envelope",
        overlay_id="homeworld-planet-envelope-7",
        fill_color="#f97316",
        fill_opacity=0.0,
        disks=(
            MapRegionOverlayDisk(x=100, y=200, radius=81),
            MapRegionOverlayDisk(x=100, y=200, radius=162),
        ),
        is_pinned=True,
        status="ok",
        candidate_count=1,
    )
    wire = map_region_overlay_to_wire(overlay)
    assert wire["geometry"] == {
        "type": "boundary",
        "vertices": [],
        "edges": [],
        "disks": [
            {"x": 100, "y": 200, "radius": 81},
            {"x": 100, "y": 200, "radius": 162},
        ],
    }

def test_possible_owners_wire_includes_optional_player_label():
    overlay = boundary_to_overlay(
        kind="homeworld-sector",
        overlay_id="sector-1",
        fill_color="#f97316",
        fill_opacity=0.2,
        vertices=(
            MapRegionOverlayVertex(x=200.0, y=0.0),
            MapRegionOverlayVertex(x=0.0, y=200.0),
            MapRegionOverlayVertex(x=0.0, y=100.0),
            MapRegionOverlayVertex(x=100.0, y=0.0),
        ),
        edges=(
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=False),
            MapRegionBoundaryLineEdge(),
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=True),
            MapRegionBoundaryLineEdge(),
        ),
        is_pinned=False,
        status="ok",
        candidate_count=2,
        possible_owners=(
            MapRegionPossibleOwner(
                owner_slot=3,
                provenance_kinds=("ship_travel_envelope",),
                player_label="alice (The Federation)",
            ),
            MapRegionPossibleOwner(
                owner_slot=5,
                provenance_kinds=("nearby_planet_ownership",),
            ),
        ),
    )
    wire = map_region_overlay_to_wire(overlay)
    assert wire["possibleOwners"] == [
        {
            "ownerSlot": 3,
            "provenanceKinds": ["ship_travel_envelope"],
            "playerLabel": "alice (The Federation)",
        },
        {
            "ownerSlot": 5,
            "provenanceKinds": ["nearby_planet_ownership"],
        },
    ]


def test_map_region_possible_owner_wire_includes_kind_counts():
    overlay = boundary_to_overlay(
        kind="homeworld-sector",
        overlay_id="homeworld-sector-0",
        fill_color="#f97316",
        fill_opacity=0.0,
        vertices=(
            MapRegionOverlayVertex(x=200.0, y=0.0),
            MapRegionOverlayVertex(x=0.0, y=200.0),
            MapRegionOverlayVertex(x=0.0, y=100.0),
            MapRegionOverlayVertex(x=100.0, y=0.0),
        ),
        edges=(
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=False),
            MapRegionBoundaryLineEdge(),
            MapRegionBoundaryArcEdge(center_x=0.0, center_y=0.0, clockwise=True),
            MapRegionBoundaryLineEdge(),
        ),
        possible_owners=(
            MapRegionPossibleOwner(
                owner_slot=3,
                provenance_kinds=("nearby_planet_ownership", "ship_travel_envelope"),
                player_label="alice (The Federation)",
                provenance_kind_counts=(
                    ("nearby_planet_ownership", 1),
                    ("ship_travel_envelope", 2),
                ),
            ),
        ),
    )
    wire = map_region_overlay_to_wire(overlay)
    assert wire["possibleOwners"] == [
        {
            "ownerSlot": 3,
            "provenanceKinds": ["nearby_planet_ownership", "ship_travel_envelope"],
            "playerLabel": "alice (The Federation)",
            "provenanceKindCounts": {
                "nearby_planet_ownership": 1,
                "ship_travel_envelope": 2,
            },
        },
    ]


def test_boundary_rejects_mismatched_edge_count():
    try:
        boundary_to_overlay(
            kind="bad",
            overlay_id="bad-1",
            fill_color="#000000",
            fill_opacity=0.1,
            vertices=(
                MapRegionOverlayVertex(x=0, y=0),
                MapRegionOverlayVertex(x=1, y=0),
                MapRegionOverlayVertex(x=0, y=1),
            ),
            edges=(MapRegionBoundaryLineEdge(), MapRegionBoundaryLineEdge()),
        )
    except ValueError as exc:
        assert "edge count" in str(exc)
    else:
        raise AssertionError("expected ValueError")


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


def test_l_shaped_nebula_chain_merges_pocket_nebula_into_one_patch():
    """L-chain AABB union leaves a pocket; a nebula there must still merge.

    Connected-component union alone emits two overlapping patch AABBs; exclusive
    blit authority requires a single non-overlapping covering AABB.
    """
    origin = CoverageOrigin(x=0, y=0, base_range=200)
    n1 = Nebula(id=1, x=0, y=0, name="A", radius=30, intensity=40)
    n2 = Nebula(id=2, x=60, y=0, name="B", radius=30, intensity=40)
    n3 = Nebula(id=3, x=0, y=60, name="C", radius=30, intensity=40)
    n4 = Nebula(id=4, x=60, y=60, name="D", radius=20, intensity=40)
    coverage = build_hybrid_coverage([origin], [n1, n2, n3, n4])

    assert len(coverage.patches) == 1
    patch = coverage.patches[0]
    assert patch.origin_x == -30
    assert patch.origin_y == -30
    assert patch.width == 121
    assert patch.height == 121
    assert patch_cell_covered(patch, 0, 0) is not None
    assert patch_cell_covered(patch, 60, 60) is not None


def test_nebula_scanner_floor_raises_reach_inside_dense_nebula():
    """Nebula Scanner keeps a 100 ly floor where V(P) would cut deeper."""
    origin = CoverageOrigin(x=0, y=0, base_range=200, has_nebula_scanner=True)
    # High intensity → V(P) at center well below 100.
    nebula = Nebula(id=1, x=100, y=0, name="Fog", radius=40, intensity=90)
    coverage = build_hybrid_coverage([origin], [nebula])
    assert len(coverage.patches) == 1
    patch = coverage.patches[0]

    density_at_center = 90.0
    visibility = nebula_visibility_ly(density_at_center)
    assert visibility is not None
    assert visibility < 100

    # Dist 100 from origin: without scanner, not covered; with floor, covered.
    assert patch_cell_covered(patch, 100, 0) is True

    plain = CoverageOrigin(x=0, y=0, base_range=200, has_nebula_scanner=False)
    plain_coverage = build_hybrid_coverage([plain], [nebula])
    plain_patch = plain_coverage.patches[0]
    assert patch_cell_covered(plain_patch, 100, 0) is False


def test_nebula_scanner_floor_capped_by_base_range_below_100():
    origin = CoverageOrigin(x=0, y=0, base_range=80, has_nebula_scanner=True)
    nebula = Nebula(id=1, x=50, y=0, name="Fog", radius=40, intensity=90)
    coverage = build_hybrid_coverage([origin], [nebula])
    patch = coverage.patches[0]
    # Dist 50 < 80 → covered by capped floor; dist 90 > 80 → not covered.
    assert patch_cell_covered(patch, 50, 0) is True
    assert patch_cell_covered(patch, 90, 0) is False
