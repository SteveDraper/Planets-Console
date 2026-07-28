"""Refine homeworld location evidence aggregates and materialize promotions."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED
from api.analytics.homeworld_locator.cull_candidates import TCullable
from api.analytics.homeworld_locator.evidence_refine_report import (
    EvidenceRefineCounts,
    EvidenceRefineInnerTimingMs,
)
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.location_evidence import (
    append_independent_origin_distance_hits,
    candidate_planet_ids,
    independent_hit_count_for_planet,
    origin_distance_candidate_planet_ids,
    promote_candidate_to_definite,
    record_single_starbase_promotion,
    ship_gravitonic_movement,
    single_starbase_new_build_implicated_planet_id,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    HomeworldIndependentEvidenceHit,
    HomeworldSingleStarbasePromotion,
)
from api.analytics.homeworld_locator.sector_overlays import (
    homeworld_layout_asset_category,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
)
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.models.game import TurnInfo
from api.models.planet import Planet


@dataclass(frozen=True)
class EvidenceRefineComputeResult:
    """Aggregate plus inner timing/counts for one refine step."""

    aggregate: HomeworldEvidenceAggregate
    timing: EvidenceRefineInnerTimingMs
    counts: EvidenceRefineCounts


def refine_homeworld_evidence_aggregate(
    prior: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
    candidate_planet_ids_set: frozenset[int],
    planets_by_id: Mapping[int, Planet],
) -> EvidenceRefineComputeResult:
    """Advance the durable evidence aggregate by one turn of observations."""
    total_t0 = time.perf_counter()
    turn_number = turn.settings.turn
    hits: tuple[HomeworldIndependentEvidenceHit, ...] = prior.evidence_hits
    prior_hit_count = len(hits)
    promotions: tuple[HomeworldSingleStarbasePromotion, ...] = prior.single_starbase_promotions
    prior_promo_count = len(promotions)
    hulls_by_id = {hull.id: hull for hull in turn.hulls}

    origin_distance_ms = 0.0
    single_starbase_ms = 0.0
    hit_append_ms = 0.0
    origin_distance_matches = 0

    for ship in turn.ships:
        gravitonic = ship_gravitonic_movement(ship, hulls_by_id=hulls_by_id)
        od_t0 = time.perf_counter()
        matched = origin_distance_candidate_planet_ids(
            ship,
            candidate_planet_ids=candidate_planet_ids_set,
            planets_by_id=planets_by_id,
            gravitonic_movement=gravitonic,
        )
        origin_distance_ms += (time.perf_counter() - od_t0) * 1000.0
        origin_distance_matches += len(matched)

        hit_t0 = time.perf_counter()
        hits = append_independent_origin_distance_hits(
            hits,
            turn=turn_number,
            matched_planet_ids=matched,
        )
        hit_append_ms += (time.perf_counter() - hit_t0) * 1000.0

        sb_t0 = time.perf_counter()
        promo_planet_id = single_starbase_new_build_implicated_planet_id(
            ship,
            turn,
            shell_turn=turn_number,
            candidate_planet_ids=candidate_planet_ids_set,
            planets_by_id=planets_by_id,
        )
        if promo_planet_id is not None:
            promotions = record_single_starbase_promotion(
                promotions,
                turn=turn_number,
                planet_id=promo_planet_id,
            )
        single_starbase_ms += (time.perf_counter() - sb_t0) * 1000.0

    aggregate = HomeworldEvidenceAggregate(
        turn=turn_number,
        baseline_turn=prior.baseline_turn,
        evidence_hits=hits,
        single_starbase_promotions=promotions,
    )
    total_ms = (time.perf_counter() - total_t0) * 1000.0
    return EvidenceRefineComputeResult(
        aggregate=aggregate,
        timing=EvidenceRefineInnerTimingMs(
            origin_distance_ms=origin_distance_ms,
            single_starbase_ms=single_starbase_ms,
            hit_append_ms=hit_append_ms,
            total_ms=total_ms,
        ),
        counts=EvidenceRefineCounts(
            ship_count=len(turn.ships),
            candidate_count=len(candidate_planet_ids_set),
            prior_hit_count=prior_hit_count,
            origin_distance_matches=origin_distance_matches,
            new_hits_appended=len(hits) - prior_hit_count,
            single_starbase_promotions=len(promotions) - prior_promo_count,
        ),
    )


def apply_threshold_evidence_promotions(
    candidates: Sequence[HomeworldCandidateRecord],
    hits: Sequence[HomeworldIndependentEvidenceHit],
    *,
    threshold: int,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Promote possibles that reached the independent-hit threshold."""
    promoted: tuple[HomeworldCandidateRecord, ...] = tuple(candidates)
    for row in candidates:
        if row.confidence_tier != CONFIDENCE_POSSIBLE:
            continue
        if independent_hit_count_for_planet(hits, row.planet_id) >= threshold:
            promoted = promote_candidate_to_definite(promoted, planet_id=row.planet_id)
    return promoted


def apply_recorded_single_starbase_promotions(
    candidates: Sequence[HomeworldCandidateRecord],
    promotions: Sequence[HomeworldSingleStarbasePromotion],
) -> tuple[HomeworldCandidateRecord, ...]:
    """Apply immediate single-starbase promotions recorded in the evidence aggregate."""
    promoted: tuple[HomeworldCandidateRecord, ...] = tuple(candidates)
    for promotion in promotions:
        promoted = promote_candidate_to_definite(promoted, planet_id=promotion.planet_id)
    return promoted


def cull_definite_neighborhood_candidates(
    candidates: Sequence[TCullable],
    planets_by_id: Mapping[int, Planet],
    *,
    min_separation_ly: float,
) -> tuple[TCullable, ...]:
    """Drop inferred possibles closer than *min_separation_ly* to any definite homeworld."""
    if min_separation_ly <= 0 or not candidates:
        return tuple(candidates)

    definite_planets: list[Planet] = []
    for row in candidates:
        if row.confidence_tier != CONFIDENCE_DEFINITE:
            continue
        planet = planets_by_id.get(row.planet_id)
        if planet is not None:
            definite_planets.append(planet)
    if not definite_planets:
        return tuple(candidates)

    kept: list[TCullable] = []
    for row in candidates:
        if row.attribution == ATTRIBUTION_USER_ASSERTED:
            kept.append(row)
            continue
        if row.confidence_tier == CONFIDENCE_DEFINITE:
            kept.append(row)
            continue
        planet = planets_by_id.get(row.planet_id)
        if planet is None:
            kept.append(row)
            continue
        too_close = any(
            distance_ly(planet.x, planet.y, definite.x, definite.y) < min_separation_ly - 1e-9
            for definite in definite_planets
        )
        if too_close:
            continue
        kept.append(row)
    return tuple(kept)


def neighbor_separation_support_min(
    turn: TurnInfo,
    *,
    player_count: int,
    layout_asset: LayoutDistributionsAsset | None = None,
) -> float | None:
    """Return layout asset neighbor ``supportMin`` when category is epic|standard."""
    category = homeworld_layout_asset_category(turn, player_count=player_count)
    if category is None:
        return None
    asset = layout_asset if layout_asset is not None else load_default_layout_distributions_asset()
    return asset.for_category(category).neighbor_separation.support_min


def materialize_evidence_adjusted_candidates(
    candidates: Sequence[HomeworldCandidateRecord],
    aggregate: HomeworldEvidenceAggregate,
    *,
    planets: Sequence[Planet],
    settings_turn: TurnInfo,
    player_count: int,
    promotion_threshold: int,
    layout_asset: LayoutDistributionsAsset | None = None,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Promotion then co-sector cull then definite-neighborhood cull.

    These are the pre-layout-prior steps of the §4.3.1 materialize ladder.
    Shell map/table serving uses ``materialize_homeworld_candidates``, which
    owns the full order through layout-prior annotation.
    """
    from api.analytics.homeworld_locator.baseline import apply_co_sector_candidate_cull

    adjusted = apply_threshold_evidence_promotions(
        candidates,
        aggregate.evidence_hits,
        threshold=promotion_threshold,
    )
    adjusted = apply_recorded_single_starbase_promotions(
        adjusted,
        aggregate.single_starbase_promotions,
    )
    adjusted = apply_co_sector_candidate_cull(
        adjusted,
        planets,
        settings=settings_turn.settings,
        player_count=player_count,
    )
    min_separation = neighbor_separation_support_min(
        settings_turn,
        player_count=player_count,
        layout_asset=layout_asset,
    )
    if min_separation is not None:
        planets_by_id = {planet.id: planet for planet in planets}
        adjusted = cull_definite_neighborhood_candidates(
            adjusted,
            planets_by_id,
            min_separation_ly=min_separation,
        )
    return adjusted


def candidate_planet_ids_from_records(
    candidates: Sequence[HomeworldCandidateRecord],
) -> frozenset[int]:
    return candidate_planet_ids(candidates)
