"""Planet-centered 81/162 LY envelope overlays when sector wedges are absent.

Emitted for sidebar-qualifying candidates (definite + slot-anchored, or
location assert with ownership bind). Sole owner of sidebar-qualifying policy;
FE player tiles derive membership from these overlay planet ids.
"""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE
from api.analytics.homeworld_locator.sector_overlays import (
    SECTOR_COLOR,
    STATUS_OK,
    envelope_disks_at,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldCandidateView,
)
from api.concepts.map_region_coverage import MapRegionOverlay, disks_to_boundary_overlay
from api.models.game import TurnInfo
from api.models.planet import Planet

KIND_HOMEWORLD_PLANET_ENVELOPE = "homeworld-planet-envelope"


def is_homeworld_sidebar_player_candidate(row: HomeworldCandidateRecord) -> bool:
    """True when ``row`` qualifies for a player-tile sidebar section.

    Slot-anchored (``perspective`` set) and either machine definite or location
    asserted. Callers filter by ``perspective`` when binding to a roster player.
    """
    if row.perspective is None:
        return False
    if row.confidence_tier == CONFIDENCE_DEFINITE:
        return True
    return row.location_asserted is True


def build_homeworld_planet_envelope_overlays(
    *,
    planets: Sequence[Planet],
    candidates: Sequence[HomeworldCandidateRecord],
) -> tuple[MapRegionOverlay, ...]:
    """One disks-only boundary overlay per sidebar-qualifying candidate planet."""
    by_id = {planet.id: planet for planet in planets}
    overlays: list[MapRegionOverlay] = []
    for row in sorted(candidates, key=lambda c: c.planet_id):
        if not is_homeworld_sidebar_player_candidate(row):
            continue
        planet = by_id.get(row.planet_id)
        if planet is None:
            continue
        overlays.append(
            disks_to_boundary_overlay(
                kind=KIND_HOMEWORLD_PLANET_ENVELOPE,
                overlay_id=f"homeworld-planet-envelope-{planet.id}",
                fill_color=SECTOR_COLOR,
                fill_opacity=0.0,
                disks=envelope_disks_at(float(planet.x), float(planet.y)),
                is_pinned=True,
                status=STATUS_OK,
                candidate_count=1,
            )
        )
    return tuple(overlays)


def build_homeworld_planet_envelope_overlays_for_turn(
    turn: TurnInfo,
    view: HomeworldCandidateView,
) -> tuple[MapRegionOverlay, ...]:
    """Emit planet envelopes for the shell turn when sector wedges are absent."""
    return build_homeworld_planet_envelope_overlays(
        planets=turn.planets,
        candidates=view.candidates,
    )
