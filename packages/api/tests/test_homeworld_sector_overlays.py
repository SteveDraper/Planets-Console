"""Unit tests for homeworld sector regionOverlays emission."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.layout_distributions_asset import (
    CategoryLayoutDistributions,
    LayoutDistributionsAsset,
    SmoothedMetricDistribution,
)
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.sector_overlays import (
    ENVELOPE_RADII_LY,
    HOVER_NO_CANDIDATES,
    KIND_HOMEWORLD_SECTOR,
    STATUS_ERROR,
    STATUS_INCOMPLETE,
    STATUS_OK,
    annular_sector_boundary,
    build_homeworld_sector_overlays,
    build_homeworld_sector_overlays_for_turn,
    closest_unobserved_band_point,
    homeworld_sector_emission_eligible,
    resolve_viewpoint_pin_planet,
    sector_index_for_angle,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldCandidateView,
)
from api.concepts.homeworld_layout import (
    HW_DISTRIBUTION_CIRCULAR,
    HW_DISTRIBUTION_RANDOM_SPACED,
    MAP_SHAPE_RECTANGULAR,
    MAP_SHAPE_ROUND,
)
from api.concepts.map_region_coverage import CoverageOrigin, map_region_overlay_to_wire
from api.models.planet import Planet
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def template_planet() -> Planet:
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw, settings_defaults=raw["settings"])
    return turn.planets[0]


@pytest.fixture
def sample_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def _planet(
    template: Planet,
    *,
    planet_id: int,
    x: int,
    y: int,
    ownerid: int = 0,
) -> Planet:
    return replace(
        template,
        id=planet_id,
        name=f"P{planet_id}",
        x=x,
        y=y,
        ownerid=ownerid,
        clans=0,
        temp=50,
        debrisdisk=0,
    )


def _stub_layout_asset(*, support_min: float = 500.0, support_max: float = 600.0):
    metric = SmoothedMetricDistribution(
        sample_count=10,
        support_min=support_min,
        support_max=support_max,
        percentiles=tuple(support_min + (support_max - support_min) * i / 100 for i in range(101)),
    )
    category = CategoryLayoutDistributions(
        center_distance=metric,
        neighbor_separation=metric,
    )
    return LayoutDistributionsAsset(
        schema_version=1,
        bin_width_ly=10.0,
        smoothing_method="laplace",
        laplace_alpha=1.0,
        percentile_step=1,
        categories={"epic": category, "standard": category},
        source={},
    )


def test_sector_index_centers_on_pin_angle() -> None:
    pin_angle = 0.0
    player_count = 4
    assert sector_index_for_angle(0.0, pin_angle=pin_angle, player_count=player_count) == 0
    assert sector_index_for_angle(math.pi / 2, pin_angle=pin_angle, player_count=player_count) == 1
    assert sector_index_for_angle(math.pi, pin_angle=pin_angle, player_count=player_count) == 2
    assert sector_index_for_angle(-math.pi / 2, pin_angle=pin_angle, player_count=player_count) == 3


def test_annular_sector_boundary_has_four_edges() -> None:
    vertices, edges = annular_sector_boundary(
        center=(0.0, 0.0),
        angle_start=0.0,
        angle_end=math.pi / 2,
        r_inner=100.0,
        r_outer=200.0,
    )
    assert len(vertices) == 4
    assert len(edges) == 4
    assert edges[0].type == "arc" and edges[0].clockwise is False
    assert edges[1].type == "line"
    assert edges[2].type == "arc" and edges[2].clockwise is True
    assert edges[3].type == "line"


def test_emission_gate_requires_pin_circular_round_epic_or_standard(sample_turn, template_planet):
    pin = _planet(template_planet, planet_id=1, x=2500, y=2000)
    # Sample turn: circular+round but only 3 players → UNKNOWN category.
    assert homeworld_sector_emission_eligible(sample_turn, pin=pin, player_count=3) is False
    assert homeworld_sector_emission_eligible(sample_turn, pin=None, player_count=11) is False

    eligible_settings = replace(
        sample_turn.settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        shiplimit=500,
        endturn=100,
        campaignmode=False,
    )
    eligible_turn = replace(sample_turn, settings=eligible_settings)
    assert homeworld_sector_emission_eligible(eligible_turn, pin=pin, player_count=11) is True

    non_circular = replace(
        eligible_turn,
        settings=replace(eligible_settings, hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED),
    )
    assert homeworld_sector_emission_eligible(non_circular, pin=pin, player_count=11) is False

    non_round = replace(
        eligible_turn,
        settings=replace(eligible_settings, mapshape=MAP_SHAPE_RECTANGULAR),
    )
    assert homeworld_sector_emission_eligible(non_round, pin=pin, player_count=11) is False


def test_build_overlays_sector_count_band_and_pin(template_planet) -> None:
    center = (2000.0, 2000.0)
    player_count = 4
    radius = 550.0
    r_inner, r_outer = 500.0, 600.0
    planets: list[Planet] = []
    candidate_ids: set[int] = set()
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        planet = _planet(
            template_planet,
            planet_id=index + 1,
            x=int(round(center[0] + radius * math.cos(angle))),
            y=int(round(center[1] + radius * math.sin(angle))),
            ownerid=1 if index == 0 else 0,
        )
        planets.append(planet)
        candidate_ids.add(planet.id)
    pin = planets[0]

    # Full coverage: origin at center with huge range.
    origins = [CoverageOrigin(x=2000, y=2000, base_range=5000)]
    overlays = build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=player_count,
        r_inner=r_inner,
        r_outer=r_outer,
        planets=planets,
        candidate_planet_ids=frozenset(candidate_ids),
        slot_anchored_planet_ids=frozenset({pin.id}),
        scan_origins=origins,
        nebulas=(),
    )
    assert len(overlays) == player_count
    # isPinned = HW determined + owning player known (slot-anchored), not mere orphans.
    pinned = [overlay for overlay in overlays if overlay.is_pinned]
    assert len(pinned) == 1
    assert pinned[0].id == "homeworld-sector-0"
    assert pinned[0].status == STATUS_OK
    assert pinned[0].geometry.type == "boundary"
    assert len(pinned[0].geometry.disks) == 2
    assert {disk.radius for disk in pinned[0].geometry.disks} == set(ENVELOPE_RADII_LY)
    assert pinned[0].geometry.disks[0].x == pin.x
    assert pinned[0].geometry.disks[0].y == pin.y
    orphan_sectors = [overlay for overlay in overlays if not overlay.is_pinned]
    assert len(orphan_sectors) == player_count - 1
    assert all(overlay.is_pinned is False for overlay in orphan_sectors)

    for overlay in overlays:
        verts = overlay.geometry.vertices
        assert abs(math.hypot(verts[0].x - center[0], verts[0].y - center[1]) - r_outer) < 1e-6
        assert abs(math.hypot(verts[2].x - center[0], verts[2].y - center[1]) - r_inner) < 1e-6
        assert overlay.kind == KIND_HOMEWORLD_SECTOR
        wire = map_region_overlay_to_wire(overlay)
        assert wire["geometry"]["type"] == "boundary"
        assert "isPinned" in wire
        assert "status" in wire
        assert "hoverSummary" in wire


def test_fully_observed_zero_candidates_error_no_disks(template_planet) -> None:
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=550, y=0)
    # Only the pin is a candidate; other sectors empty under full observation.
    origins = [CoverageOrigin(x=0, y=0, base_range=5000)]
    overlays = build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=4,
        r_inner=500.0,
        r_outer=600.0,
        planets=[pin],
        candidate_planet_ids=frozenset({pin.id}),
        slot_anchored_planet_ids=frozenset({pin.id}),
        scan_origins=origins,
        nebulas=(),
    )
    assert len(overlays) == 4
    pinned = next(overlay for overlay in overlays if overlay.is_pinned)
    assert pinned.status == STATUS_OK
    assert len(pinned.geometry.disks) == 2

    errors = [overlay for overlay in overlays if overlay.status == STATUS_ERROR]
    assert len(errors) == 3
    for overlay in errors:
        assert overlay.geometry.disks == ()
        assert overlay.hover_summary == HOVER_NO_CANDIDATES
        assert overlay.fill_color.startswith("#ef")


def test_incomplete_observation_uses_unobserved_point(template_planet) -> None:
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=550, y=0)
    # Tiny scan near pin only — opposite sectors remain unobserved.
    origins = [CoverageOrigin(x=550, y=0, base_range=20)]
    unobserved = closest_unobserved_band_point(
        center=center,
        angle_start=math.pi - math.pi / 4,
        angle_end=math.pi + math.pi / 4,
        r_inner=500.0,
        r_outer=600.0,
        origins=origins,
        nebulas=(),
    )
    assert unobserved is not None
    assert abs(math.hypot(unobserved[0], unobserved[1]) - 500.0) < 1.0

    overlays = build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=4,
        r_inner=500.0,
        r_outer=600.0,
        planets=[pin],
        candidate_planet_ids=frozenset({pin.id}),
        slot_anchored_planet_ids=frozenset({pin.id}),
        scan_origins=origins,
        nebulas=(),
    )
    opposite = next(overlay for overlay in overlays if overlay.id == "homeworld-sector-2")
    assert opposite.is_pinned is False
    assert opposite.status == STATUS_INCOMPLETE
    assert len(opposite.geometry.disks) == 2
    # Envelope sits on the inner arc (closest unobserved to C).
    disk = opposite.geometry.disks[0]
    assert abs(math.hypot(disk.x, disk.y) - 500.0) < 2.0


def test_envelope_center_closest_candidate_to_map_center(template_planet) -> None:
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=550, y=0)
    # Two orphan candidates in sector 1 (around +π/2): nearer and farther from C.
    near = _planet(template_planet, planet_id=2, x=0, y=520)
    far = _planet(template_planet, planet_id=3, x=0, y=580)
    origins = [CoverageOrigin(x=0, y=0, base_range=5000)]
    overlays = build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=4,
        r_inner=500.0,
        r_outer=600.0,
        planets=[pin, near, far],
        candidate_planet_ids=frozenset({pin.id, near.id, far.id}),
        slot_anchored_planet_ids=frozenset({pin.id}),
        scan_origins=origins,
        nebulas=(),
    )
    sector_one = next(overlay for overlay in overlays if overlay.id == "homeworld-sector-1")
    assert sector_one.status == STATUS_OK
    assert sector_one.is_pinned is False
    assert sector_one.geometry.disks[0].x == near.x
    assert sector_one.geometry.disks[0].y == near.y


def test_incomplete_with_candidates_prefers_candidate_center(template_planet) -> None:
    """Fog elsewhere in the sector must not displace envelopes off known candidates."""
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=550, y=0)
    orphan = _planet(template_planet, planet_id=2, x=0, y=520)
    # Scan covers only the pin; sector 1 remains incompletely observed.
    origins = [CoverageOrigin(x=550, y=0, base_range=30)]
    overlays = build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=4,
        r_inner=500.0,
        r_outer=600.0,
        planets=[pin, orphan],
        candidate_planet_ids=frozenset({pin.id, orphan.id}),
        slot_anchored_planet_ids=frozenset({pin.id}),
        scan_origins=origins,
        nebulas=(),
    )
    sector_one = next(overlay for overlay in overlays if overlay.id == "homeworld-sector-1")
    assert sector_one.is_pinned is False
    assert sector_one.status == STATUS_INCOMPLETE
    assert sector_one.geometry.disks[0].x == orphan.x
    assert sector_one.geometry.disks[0].y == orphan.y


def test_resolve_viewpoint_pin_planet(template_planet) -> None:
    pin = _planet(template_planet, planet_id=42, x=1, y=2)
    other = _planet(template_planet, planet_id=99, x=3, y=4)
    view = HomeworldCandidateView(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=99,
                perspective=None,
                confidence_tier=CONFIDENCE_POSSIBLE,
            ),
            HomeworldCandidateRecord(
                planet_id=42,
                perspective=1,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
        ),
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )
    assert resolve_viewpoint_pin_planet(view, [pin, other]) is pin
    assert resolve_viewpoint_pin_planet(view, [other]) is None


def test_stub_asset_band_used_by_builder(template_planet) -> None:
    asset = _stub_layout_asset(support_min=510.0, support_max=590.0)
    assert asset.center_distance_band("epic") == (510.0, 590.0)


def test_for_turn_emits_when_gate_passes_and_empty_without_pin(
    sample_turn, template_planet
) -> None:
    asset = _stub_layout_asset(support_min=500.0, support_max=600.0)
    players = [
        replace(sample_turn.player, id=index + 1, username=f"p{index + 1}") for index in range(11)
    ]
    center = (2000.0, 2000.0)
    pin = _planet(template_planet, planet_id=1, x=2550, y=2000, ownerid=players[0].id)
    settings = replace(
        sample_turn.settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        shiplimit=500,
        endturn=100,
        campaignmode=False,
        planetscanrange=10000,
    )
    turn = replace(
        sample_turn,
        settings=settings,
        player=players[0],
        players=players,
        planets=[pin],
        ships=[],
        relations=[],
    )
    view = HomeworldCandidateView(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=pin.id,
                perspective=1,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
        ),
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )
    overlays = build_homeworld_sector_overlays_for_turn(
        turn,
        view,
        layout_asset=asset,
        map_center=center,
    )
    assert len(overlays) == 11
    assert sum(1 for overlay in overlays if overlay.is_pinned) == 1

    no_pin_view = HomeworldCandidateView(
        candidates=(),
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )
    assert (
        build_homeworld_sector_overlays_for_turn(
            turn, no_pin_view, layout_asset=asset, map_center=center
        )
        == ()
    )
