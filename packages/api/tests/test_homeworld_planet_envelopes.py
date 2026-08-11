"""Unit tests for planet-centered homeworld envelope overlays."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.planet_envelopes import (
    KIND_HOMEWORLD_PLANET_ENVELOPE,
    build_homeworld_planet_envelope_overlays,
    build_homeworld_planet_envelope_overlays_for_turn,
    is_homeworld_sidebar_player_candidate,
)
from api.analytics.homeworld_locator.sector_overlays import ENVELOPE_RADII_LY
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.concepts.map_region_coverage import MapRegionOverlayDisk, disks_to_boundary_overlay
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

def test_disks_to_boundary_overlay_requires_disks() -> None:
    with pytest.raises(ValueError, match="at least one disk"):
        disks_to_boundary_overlay(
            kind=KIND_HOMEWORLD_PLANET_ENVELOPE,
            overlay_id="empty",
            fill_color="#f97316",
            fill_opacity=0.0,
            disks=(),
        )


def test_disks_to_boundary_overlay_empty_path() -> None:
    overlay = disks_to_boundary_overlay(
        kind=KIND_HOMEWORLD_PLANET_ENVELOPE,
        overlay_id="homeworld-planet-envelope-9",
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
    assert overlay.geometry.type == "boundary"
    assert overlay.geometry.vertices == ()
    assert overlay.geometry.edges == ()
    assert {d.radius for d in overlay.geometry.disks} == set(ENVELOPE_RADII_LY)


def test_sidebar_qualify_predicate_matches_phase2_policy() -> None:
    assert (
        is_homeworld_sidebar_player_candidate(
            HomeworldCandidateRecord(
                planet_id=1,
                perspective=2,
                confidence_tier=CONFIDENCE_DEFINITE,
            )
        )
        is True
    )
    assert (
        is_homeworld_sidebar_player_candidate(
            HomeworldCandidateRecord(
                planet_id=2,
                perspective=2,
                confidence_tier=CONFIDENCE_POSSIBLE,
                location_asserted=True,
            )
        )
        is True
    )
    assert (
        is_homeworld_sidebar_player_candidate(
            HomeworldCandidateRecord(
                planet_id=3,
                perspective=2,
                confidence_tier=CONFIDENCE_POSSIBLE,
            )
        )
        is False
    )
    assert (
        is_homeworld_sidebar_player_candidate(
            HomeworldCandidateRecord(
                planet_id=4,
                perspective=None,
                confidence_tier=CONFIDENCE_DEFINITE,
            )
        )
        is False
    )
    assert (
        is_homeworld_sidebar_player_candidate(
            HomeworldCandidateRecord(
                planet_id=5,
                perspective=None,
                confidence_tier=CONFIDENCE_POSSIBLE,
                location_asserted=True,
            )
        )
        is False
    )


def test_build_planet_envelopes_only_for_qualifying_planets(template_planet) -> None:
    pinned = replace(template_planet, id=10, x=1000, y=2000)
    asserted = replace(template_planet, id=20, x=1100, y=2100)
    possible = replace(template_planet, id=30, x=1200, y=2200)
    missing = replace(template_planet, id=40, x=1300, y=2300)

    overlays = build_homeworld_planet_envelope_overlays(
        planets=[pinned, asserted, possible],
        candidates=(
            HomeworldCandidateRecord(
                planet_id=pinned.id,
                perspective=1,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
            HomeworldCandidateRecord(
                planet_id=asserted.id,
                perspective=2,
                confidence_tier=CONFIDENCE_POSSIBLE,
                location_asserted=True,
            ),
            HomeworldCandidateRecord(
                planet_id=possible.id,
                perspective=3,
                confidence_tier=CONFIDENCE_POSSIBLE,
            ),
            HomeworldCandidateRecord(
                planet_id=missing.id,
                perspective=4,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
        ),
    )
    assert [o.id for o in overlays] == [
        "homeworld-planet-envelope-10",
        "homeworld-planet-envelope-20",
    ]
    for overlay in overlays:
        assert overlay.kind == KIND_HOMEWORLD_PLANET_ENVELOPE
        assert overlay.geometry.vertices == ()
        assert {d.radius for d in overlay.geometry.disks} == set(ENVELOPE_RADII_LY)
    assert overlays[0].geometry.disks[0].x == 1000
    assert overlays[0].geometry.disks[0].y == 2000
    assert overlays[1].geometry.disks[0].x == 1100
    assert overlays[1].geometry.disks[0].y == 2100


def test_for_turn_emits_planet_envelopes(sample_turn, template_planet) -> None:
    planet = replace(template_planet, id=7, x=2550, y=2000)
    turn = replace(sample_turn, planets=[planet])
    view = HomeworldCandidateView(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=planet.id,
                perspective=1,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
        ),
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )
    overlays = build_homeworld_planet_envelope_overlays_for_turn(turn, view)
    assert len(overlays) == 1
    assert overlays[0].id == "homeworld-planet-envelope-7"
