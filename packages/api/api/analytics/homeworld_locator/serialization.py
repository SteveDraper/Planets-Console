"""JSON codecs for homeworld locator persistence documents."""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
    HomeworldSingleStarbasePromotion,
    OriginDistanceObservation,
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


def _origin_distance_observation_to_json(observation: OriginDistanceObservation) -> dict[str, Any]:
    return {
        "turn": observation.turn,
        "x": observation.x,
        "y": observation.y,
        "matchedPlanetIds": list(observation.matched_planet_ids),
    }


def _origin_distance_observation_from_json(data: dict[str, Any]) -> OriginDistanceObservation:
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld origin-distance observation turn must be an int >= 1")
    x = data.get("x")
    if not isinstance(x, int):
        raise ValidationError("homeworld origin-distance observation x must be an int")
    y = data.get("y")
    if not isinstance(y, int):
        raise ValidationError("homeworld origin-distance observation y must be an int")
    matched_raw = data.get("matchedPlanetIds")
    if not isinstance(matched_raw, list) or not all(isinstance(item, int) for item in matched_raw):
        raise ValidationError(
            "homeworld origin-distance observation matchedPlanetIds must be an int array"
        )
    if not matched_raw:
        raise ValidationError(
            "homeworld origin-distance observation matchedPlanetIds must be non-empty"
        )
    return OriginDistanceObservation(
        turn=turn,
        x=x,
        y=y,
        matched_planet_ids=tuple(matched_raw),
    )


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
    payload: dict[str, Any] = {
        "turn": aggregate.turn,
        "baselineTurn": aggregate.baseline_turn,
        "originDistanceObservations": [
            _origin_distance_observation_to_json(observation)
            for observation in aggregate.origin_distance_observations
        ],
        "singleStarbasePromotions": [
            _single_starbase_promotion_to_json(promotion)
            for promotion in aggregate.single_starbase_promotions
        ],
    }
    if aggregate.origin_distance_evidence_through_turn is not None:
        payload["originDistanceEvidenceThroughTurn"] = (
            aggregate.origin_distance_evidence_through_turn
        )
    if aggregate.layout_prior_algorithm_version is not None:
        selection: dict[str, Any] = {
            "algorithmVersion": aggregate.layout_prior_algorithm_version,
            "inputFingerprint": [
                {
                    "planetId": planet_id,
                    "confidenceTier": tier,
                    "perspective": perspective,
                }
                for planet_id, tier, perspective in aggregate.layout_prior_input_fingerprint
            ],
            "mostProbablePlanetIds": list(aggregate.most_probable_planet_ids),
        }
        if aggregate.layout_prior_promotion_threshold is not None:
            selection["promotionThreshold"] = aggregate.layout_prior_promotion_threshold
        payload["layoutPriorSelection"] = selection
    return payload


def homeworld_evidence_aggregate_from_json(data: dict[str, Any]) -> HomeworldEvidenceAggregate:
    if not isinstance(data, dict):
        raise ValidationError("homeworld evidence aggregate must be a JSON object")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld evidence aggregate turn must be an int >= 1")
    baseline_turn = data.get("baselineTurn")
    if not isinstance(baseline_turn, int) or baseline_turn < 1:
        raise ValidationError("homeworld evidence aggregate baselineTurn must be an int >= 1")
    observations_raw = data.get("originDistanceObservations", [])
    if not isinstance(observations_raw, list):
        raise ValidationError(
            "homeworld evidence aggregate originDistanceObservations must be a JSON array"
        )
    promotions_raw = data.get("singleStarbasePromotions", [])
    if not isinstance(promotions_raw, list):
        raise ValidationError(
            "homeworld evidence aggregate singleStarbasePromotions must be a JSON array"
        )
    observations = tuple(
        _origin_distance_observation_from_json(observation)
        for observation in observations_raw
        if isinstance(observation, dict)
    )
    if len(observations) != len(observations_raw):
        raise ValidationError(
            "homeworld evidence aggregate originDistanceObservations entries must be objects"
        )
    promotions = tuple(
        _single_starbase_promotion_from_json(promotion)
        for promotion in promotions_raw
        if isinstance(promotion, dict)
    )
    if len(promotions) != len(promotions_raw):
        raise ValidationError(
            "homeworld evidence aggregate singleStarbasePromotions entries must be objects"
        )
    selection_version: int | None = None
    selection_threshold: int | None = None
    selection_fingerprint: tuple[tuple[int, str, int | None], ...] = ()
    most_probable_ids: tuple[int, ...] = ()
    selection_raw = data.get("layoutPriorSelection")
    if selection_raw is not None:
        if not isinstance(selection_raw, dict):
            raise ValidationError(
                "homeworld evidence aggregate layoutPriorSelection must be an object"
            )
        version = selection_raw.get("algorithmVersion")
        if not isinstance(version, int) or version < 1:
            raise ValidationError(
                "homeworld layoutPriorSelection.algorithmVersion must be an int >= 1"
            )
        # Legacy payloads omit inputFingerprint; treat as absent so materialize recomputes.
        if "inputFingerprint" in selection_raw:
            if "promotionThreshold" in selection_raw:
                threshold = selection_raw.get("promotionThreshold")
                if not isinstance(threshold, int) or threshold < 1:
                    raise ValidationError(
                        "homeworld layoutPriorSelection.promotionThreshold must be an int >= 1"
                    )
                selection_threshold = threshold
            fingerprint_raw = selection_raw.get("inputFingerprint")
            if not isinstance(fingerprint_raw, list):
                raise ValidationError(
                    "homeworld layoutPriorSelection.inputFingerprint must be a JSON array"
                )
            fingerprint_entries: list[tuple[int, str, int | None]] = []
            for entry in fingerprint_raw:
                if not isinstance(entry, dict):
                    raise ValidationError(
                        "homeworld layoutPriorSelection.inputFingerprint entries must be objects"
                    )
                planet_id = entry.get("planetId")
                if not isinstance(planet_id, int):
                    raise ValidationError(
                        "homeworld layoutPriorSelection.inputFingerprint.planetId must be an int"
                    )
                tier = entry.get("confidenceTier")
                if tier not in _VALID_TIERS:
                    raise ValidationError(
                        "homeworld layoutPriorSelection.inputFingerprint.confidenceTier "
                        f"must be one of {sorted(_VALID_TIERS)!r}"
                    )
                perspective = entry.get("perspective")
                if perspective is not None and not isinstance(perspective, int):
                    raise ValidationError(
                        "homeworld layoutPriorSelection.inputFingerprint.perspective "
                        "must be an int or null"
                    )
                fingerprint_entries.append((planet_id, tier, perspective))
            ids_raw = selection_raw.get("mostProbablePlanetIds", [])
            if not isinstance(ids_raw, list) or not all(isinstance(item, int) for item in ids_raw):
                raise ValidationError(
                    "homeworld layoutPriorSelection.mostProbablePlanetIds must be an int array"
                )
            selection_version = version
            selection_fingerprint = tuple(fingerprint_entries)
            most_probable_ids = tuple(ids_raw)

    through_raw = data.get("originDistanceEvidenceThroughTurn")
    through_turn: int | None
    if through_raw is None:
        through_turn = None
    elif isinstance(through_raw, int) and through_raw >= 0:
        through_turn = through_raw
    else:
        raise ValidationError(
            "homeworld evidence aggregate originDistanceEvidenceThroughTurn "
            "must be an int >= 0 when present"
        )

    return HomeworldEvidenceAggregate(
        turn=turn,
        baseline_turn=baseline_turn,
        origin_distance_observations=observations,
        single_starbase_promotions=promotions,
        origin_distance_evidence_through_turn=through_turn,
        layout_prior_algorithm_version=selection_version,
        layout_prior_promotion_threshold=selection_threshold,
        layout_prior_input_fingerprint=selection_fingerprint,
        most_probable_planet_ids=most_probable_ids,
    )
