"""Unit tests for co-sector cull protection (location assert vs ownership cue).

Derive-then-cull integration coverage lives in test_homeworld_evidence_refine.py.
"""

from __future__ import annotations

import pytest
from api.analytics.homeworld_locator import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.baseline import cull_co_sector_candidates_after_definites
from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.models.planet import Planet

from tests.homeworld_locator_test_helpers import (
    _planet,
    load_sample_template_planet,
)


@pytest.fixture
def template_planet() -> Planet:
    return load_sample_template_planet()


def test_cull_drops_ownership_cued_co_sector_possibles(template_planet) -> None:
    """Sector ownership lights asserted_cue on every candidate; that must not block cull."""
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=45, x=500, y=0)
    other_a = _planet(template_planet, planet_id=69, x=550, y=20)
    other_b = _planet(template_planet, planet_id=87, x=520, y=30)
    other_c = _planet(template_planet, planet_id=130, x=480, y=25)
    rows = (
        HomeworldCandidateRecord(
            planet_id=45,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
            asserted_cue=True,
            location_asserted=True,
        ),
        HomeworldCandidateRecord(
            planet_id=69,
            perspective=1,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
            asserted_cue=True,
        ),
        HomeworldCandidateRecord(
            planet_id=87,
            perspective=1,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
            asserted_cue=True,
        ),
        HomeworldCandidateRecord(
            planet_id=130,
            perspective=1,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
            asserted_cue=True,
        ),
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        {45: pin, 69: other_a, 87: other_b, 130: other_c},
        center=center,
        player_count=4,
        pin_angle=0.0,
        protected_planet_ids=frozenset({45}),
    )
    assert {row.planet_id for row in culled} == {45}


def test_cull_preserves_location_asserted_co_sector_possible(template_planet) -> None:
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=500, y=0)
    asserted = _planet(template_planet, planet_id=2, x=550, y=20)
    rows = (
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=2,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
            location_asserted=True,
        ),
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        {1: pin, 2: asserted},
        center=center,
        player_count=4,
        pin_angle=0.0,
    )
    assert {row.planet_id for row in culled} == {1, 2}


def test_cull_is_noop_when_location_assert_revoked_leaves_no_definite(
    template_planet,
) -> None:
    """Revoke drops the definite pin; co-sector cull then keeps ownership-cued possibles."""
    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=45, x=500, y=0)
    other_a = _planet(template_planet, planet_id=69, x=550, y=20)
    other_b = _planet(template_planet, planet_id=87, x=520, y=30)
    other_c = _planet(template_planet, planet_id=130, x=480, y=25)
    rows = tuple(
        HomeworldCandidateRecord(
            planet_id=planet_id,
            perspective=1,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
            asserted_cue=True,
        )
        for planet_id in (45, 69, 87, 130)
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        {45: pin, 69: other_a, 87: other_b, 130: other_c},
        center=center,
        player_count=4,
        pin_angle=0.0,
    )
    assert {row.planet_id for row in culled} == {45, 69, 87, 130}
