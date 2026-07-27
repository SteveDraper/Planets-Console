"""JSON codecs for homeworld locator persistence documents."""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    EVIDENCE_KIND_ORIGIN_DISTANCE,
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
    HomeworldIndependentEvidenceHit,
    HomeworldSingleStarbasePromotion,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)
from api.errors import ValidationError

_VALID_TIERS = frozenset({CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE})


def homeworld_candidate_record_to_json(record: HomeworldCandidateRecord) -> dict[str, Any]:
    return {
        "planetId": record.planet_id,
        "perspective": record.perspective,
        "confidenceTier": record.confidence_tier,
        "attribution": record.attribution,
    }


def homeworld_candidate_record_from_json(data: dict[str, Any]) -> HomeworldCandidateRecord:
    if not isinstance(data, dict):
        raise ValidationError("homeworld candidate record must be a JSON object")
    planet_id = data.get("planetId")
    if not isinstance(planet_id, int):
        raise ValidationError("homeworld candidate planetId must be an int")
    perspective = data.get("perspective")
    if perspective is not None and not isinstance(perspective, int):
        raise ValidationError("homeworld candidate perspective must be an int or null")
    tier = data.get("confidenceTier")
    if tier not in _VALID_TIERS:
        raise ValidationError(
            f"homeworld candidate confidenceTier must be one of {sorted(_VALID_TIERS)!r}"
        )
    attribution = data.get("attribution", ATTRIBUTION_INFERRED)
    if not isinstance(attribution, str) or not attribution:
        raise ValidationError("homeworld candidate attribution must be a non-empty string")
    return HomeworldCandidateRecord(
        planet_id=planet_id,
        perspective=perspective,
        confidence_tier=tier,
        attribution=attribution,
    )


def homeworld_locator_game_state_to_json(state: HomeworldLocatorGameState) -> dict[str, Any]:
    return {
        "candidates": [homeworld_candidate_record_to_json(row) for row in state.candidates],
        "baselineTurn": state.baseline_turn,
        "baselineDegraded": state.baseline_degraded,
        "settingsFingerprint": list(state.settings_fingerprint),
    }


def homeworld_locator_game_state_from_json(data: dict[str, Any]) -> HomeworldLocatorGameState:
    if not isinstance(data, dict):
        raise ValidationError("homeworld locator game state must be a JSON object")
    candidates_raw = data.get("candidates", [])
    if not isinstance(candidates_raw, list):
        raise ValidationError("homeworld locator candidates must be a JSON array")
    baseline_turn = data.get("baselineTurn")
    if not isinstance(baseline_turn, int) or baseline_turn < 1:
        raise ValidationError("homeworld locator baselineTurn must be an int >= 1")
    baseline_degraded = data.get("baselineDegraded", False)
    if not isinstance(baseline_degraded, bool):
        raise ValidationError("homeworld locator baselineDegraded must be a bool")
    fingerprint_raw = data.get("settingsFingerprint", [])
    if not isinstance(fingerprint_raw, list):
        raise ValidationError("homeworld locator settingsFingerprint must be a JSON array")
    return HomeworldLocatorGameState(
        candidates=tuple(homeworld_candidate_record_from_json(row) for row in candidates_raw),
        baseline_turn=baseline_turn,
        baseline_degraded=baseline_degraded,
        settings_fingerprint=tuple(fingerprint_raw),
    )


def _evidence_hit_to_json(hit: HomeworldIndependentEvidenceHit) -> dict[str, Any]:
    return {
        "planetId": hit.planet_id,
        "turn": hit.turn,
        "kind": hit.kind,
    }


def _evidence_hit_from_json(data: dict[str, Any]) -> HomeworldIndependentEvidenceHit:
    planet_id = data.get("planetId")
    if not isinstance(planet_id, int):
        raise ValidationError("homeworld evidence hit planetId must be an int")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld evidence hit turn must be an int >= 1")
    kind = data.get("kind", EVIDENCE_KIND_ORIGIN_DISTANCE)
    if kind != EVIDENCE_KIND_ORIGIN_DISTANCE:
        raise ValidationError(
            f"homeworld evidence hit kind must be {EVIDENCE_KIND_ORIGIN_DISTANCE!r}"
        )
    return HomeworldIndependentEvidenceHit(planet_id=planet_id, turn=turn, kind=kind)


def _single_starbase_promotion_to_json(
    promotion: HomeworldSingleStarbasePromotion,
) -> dict[str, Any]:
    return {
        "planetId": promotion.planet_id,
        "turn": promotion.turn,
        "kind": promotion.kind,
    }


def _single_starbase_promotion_from_json(
    data: dict[str, Any],
) -> HomeworldSingleStarbasePromotion:
    planet_id = data.get("planetId")
    if not isinstance(planet_id, int):
        raise ValidationError("homeworld single-starbase promotion planetId must be an int")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld single-starbase promotion turn must be an int >= 1")
    kind = data.get("kind", EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD)
    if kind != EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD:
        raise ValidationError(
            "homeworld single-starbase promotion kind must be "
            f"{EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD!r}"
        )
    return HomeworldSingleStarbasePromotion(planet_id=planet_id, turn=turn, kind=kind)


def homeworld_evidence_aggregate_to_json(
    aggregate: HomeworldEvidenceAggregate,
) -> dict[str, Any]:
    return {
        "turn": aggregate.turn,
        "baselineTurn": aggregate.baseline_turn,
        "evidenceHits": [_evidence_hit_to_json(hit) for hit in aggregate.evidence_hits],
        "singleStarbasePromotions": [
            _single_starbase_promotion_to_json(promotion)
            for promotion in aggregate.single_starbase_promotions
        ],
    }


def homeworld_evidence_aggregate_from_json(data: dict[str, Any]) -> HomeworldEvidenceAggregate:
    if not isinstance(data, dict):
        raise ValidationError("homeworld evidence aggregate must be a JSON object")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld evidence aggregate turn must be an int >= 1")
    baseline_turn = data.get("baselineTurn")
    if not isinstance(baseline_turn, int) or baseline_turn < 1:
        raise ValidationError("homeworld evidence aggregate baselineTurn must be an int >= 1")
    hits_raw = data.get("evidenceHits", [])
    if not isinstance(hits_raw, list):
        raise ValidationError("homeworld evidence aggregate evidenceHits must be a JSON array")
    promotions_raw = data.get("singleStarbasePromotions", [])
    if not isinstance(promotions_raw, list):
        raise ValidationError(
            "homeworld evidence aggregate singleStarbasePromotions must be a JSON array"
        )
    hits = tuple(_evidence_hit_from_json(hit) for hit in hits_raw if isinstance(hit, dict))
    if len(hits) != len(hits_raw):
        raise ValidationError("homeworld evidence aggregate evidenceHits entries must be objects")
    promotions = tuple(
        _single_starbase_promotion_from_json(promotion)
        for promotion in promotions_raw
        if isinstance(promotion, dict)
    )
    if len(promotions) != len(promotions_raw):
        raise ValidationError(
            "homeworld evidence aggregate singleStarbasePromotions entries must be objects"
        )
    return HomeworldEvidenceAggregate(
        turn=turn,
        baseline_turn=baseline_turn,
        evidence_hits=hits,
        single_starbase_promotions=promotions,
    )
