"""JSON codecs for homeworld locator persistence documents."""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.constants import (
    ATTRIBUTION_INFERRED,
    ATTRIBUTION_USER_ASSERTED,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
    PROVENANCE_ASSERTED,
    HomeworldSingleStarbasePromotion,
    LocationProvenance,
    OriginDistanceObservation,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
    ensure_candidates_for_asserted_locations,
)
from api.errors import ValidationError

_VALID_TIERS = frozenset({CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE})


def homeworld_candidate_record_to_json(record: HomeworldCandidateRecord) -> dict[str, Any]:
    """Persist candidate shell fields only.

    ``attribution`` stays ``inferred`` on disk; ``asserted_cue`` is derived at
    materialize and is not persisted (ADR 0010). Wire emit maps
    ``asserted_cue`` → ``attribution=user_asserted`` for FE compat.
    """
    payload: dict[str, Any] = {
        "planetId": record.planet_id,
        "perspective": record.perspective,
        "confidenceTier": record.confidence_tier,
        "attribution": ATTRIBUTION_INFERRED,
    }
    if record.is_most_probable:
        payload["isMostProbable"] = True
    return payload


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
    # assertedCue on disk is ignored: cue is derived at materialize from provenances.
    is_most_probable = data.get("isMostProbable", False)
    if not isinstance(is_most_probable, bool):
        raise ValidationError("homeworld candidate isMostProbable must be a bool when present")
    return HomeworldCandidateRecord(
        planet_id=planet_id,
        perspective=perspective,
        confidence_tier=tier,
        # Preserve raw attribution only long enough for game-state migration below.
        attribution=attribution,
        asserted_cue=False,
        is_most_probable=is_most_probable,
    )


def _location_provenance_to_json(provenance: LocationProvenance) -> dict[str, Any]:
    return {
        "kind": provenance.kind,
        "turn": provenance.turn,
        "planetId": provenance.planet_id,
    }


def _location_provenance_from_json(data: dict[str, Any]) -> LocationProvenance:
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValidationError("homeworld location provenance kind must be a non-empty string")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld location provenance turn must be an int >= 1")
    planet_id = data.get("planetId")
    if not isinstance(planet_id, int) or planet_id < 1:
        raise ValidationError("homeworld location provenance planetId must be an int >= 1")
    return LocationProvenance(kind=kind, turn=turn, planet_id=planet_id)


def _location_provenances_from_json(
    raw: object,
    *,
    field_name: str,
) -> tuple[LocationProvenance, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(f"{field_name} must be a JSON array")
    rows = tuple(_location_provenance_from_json(entry) for entry in raw if isinstance(entry, dict))
    if len(rows) != len(raw):
        raise ValidationError(f"{field_name} entries must be objects")
    return rows


def homeworld_locator_game_state_to_json(state: HomeworldLocatorGameState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidates": [homeworld_candidate_record_to_json(row) for row in state.candidates],
        "baselineTurn": state.baseline_turn,
        "baselineDegraded": state.baseline_degraded,
        "settingsFingerprint": list(state.settings_fingerprint),
        "baselineAlgorithmVersion": state.baseline_algorithm_version,
    }
    if state.asserted_location_provenances:
        payload["assertedLocationProvenances"] = [
            _location_provenance_to_json(row) for row in state.asserted_location_provenances
        ]
    if state.asserted_sector_ownership:
        payload["assertedSectorOwnership"] = _sector_owner_sets_to_json(
            state.asserted_sector_ownership
        )
    if state.asserted_planet_ownership:
        payload["assertedPlanetOwnership"] = _sector_owner_sets_to_json(
            state.asserted_planet_ownership
        )
    return payload


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
    version_raw = data.get("baselineAlgorithmVersion", 0)
    if isinstance(version_raw, bool) or not isinstance(version_raw, int) or version_raw < 0:
        raise ValidationError("homeworld locator baselineAlgorithmVersion must be an int >= 0")
    candidates = tuple(homeworld_candidate_record_from_json(row) for row in candidates_raw)
    asserted_location = _location_provenances_from_json(
        data.get("assertedLocationProvenances"),
        field_name="homeworld locator assertedLocationProvenances",
    )
    # Single read-path migration: legacy attribution=user_asserted → asserted locations.
    if not asserted_location:
        migrated: list[LocationProvenance] = []
        for row in candidates:
            if row.attribution == ATTRIBUTION_USER_ASSERTED:
                migrated.append(
                    LocationProvenance(
                        kind=PROVENANCE_ASSERTED,
                        turn=baseline_turn,
                        planet_id=row.planet_id,
                    )
                )
        asserted_location = tuple(migrated)
    normalized = tuple(
        HomeworldCandidateRecord(
            planet_id=row.planet_id,
            perspective=row.perspective,
            confidence_tier=row.confidence_tier,
            attribution=ATTRIBUTION_INFERRED,
            is_most_probable=row.is_most_probable,
            asserted_cue=False,
        )
        for row in candidates
    )
    candidates = ensure_candidates_for_asserted_locations(
        inferred=normalized,
        asserted_location_provenances=asserted_location,
    )
    return HomeworldLocatorGameState(
        candidates=candidates,
        baseline_turn=baseline_turn,
        baseline_degraded=baseline_degraded,
        settings_fingerprint=tuple(fingerprint_raw),
        baseline_algorithm_version=version_raw,
        asserted_location_provenances=asserted_location,
        asserted_sector_ownership=_sector_owner_sets_from_json(data.get("assertedSectorOwnership")),
        asserted_planet_ownership=_sector_owner_sets_from_json(data.get("assertedPlanetOwnership")),
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


def _layout_prior_selection_to_json(aggregate: HomeworldEvidenceAggregate) -> dict[str, Any]:
    """Wire ``layoutPriorSelection``; requires a complete reuse-key on the aggregate."""
    version = aggregate.layout_prior_algorithm_version
    if version is None:
        raise ValidationError(
            "homeworld layoutPriorSelection requires layout_prior_algorithm_version"
        )
    evidence_lambda = aggregate.layout_prior_evidence_lambda
    if evidence_lambda is None:
        raise ValidationError(
            "homeworld layoutPriorSelection requires layout_prior_evidence_lambda"
        )
    evidence_fingerprint = aggregate.layout_prior_evidence_fingerprint
    if evidence_fingerprint is None:
        raise ValidationError(
            "homeworld layoutPriorSelection requires layout_prior_evidence_fingerprint"
        )
    return {
        "algorithmVersion": version,
        "inputFingerprint": [
            {
                "planetId": planet_id,
                "confidenceTier": tier,
                "perspective": perspective,
            }
            for planet_id, tier, perspective in aggregate.layout_prior_input_fingerprint
        ],
        "evidenceLambda": evidence_lambda,
        "evidenceFingerprint": evidence_fingerprint,
        "mostProbablePlanetIds": list(aggregate.most_probable_planet_ids),
    }


def _layout_prior_input_fingerprint_from_json(
    fingerprint_raw: object,
) -> tuple[tuple[int, str, int | None], ...]:
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
                "homeworld layoutPriorSelection.inputFingerprint.perspective must be an int or null"
            )
        fingerprint_entries.append((planet_id, tier, perspective))
    return tuple(fingerprint_entries)


def _layout_prior_selection_from_json(
    selection_raw: object,
) -> tuple[int, tuple[tuple[int, str, int | None], ...], float, str, tuple[int, ...]] | None:
    """Parse a complete ``layoutPriorSelection`` reuse key.

    Legacy or incomplete selections (missing reuse-key fields) return ``None`` so
    the aggregate still loads and layout-prior reuse misses. Present-but-invalid
    field types still raise ``ValidationError``.
    """
    if not isinstance(selection_raw, dict):
        raise ValidationError("homeworld evidence aggregate layoutPriorSelection must be an object")
    # Complete reuse key only; omit any required field → clear selection (reuse miss).
    required_keys = (
        "algorithmVersion",
        "inputFingerprint",
        "evidenceLambda",
        "evidenceFingerprint",
        "mostProbablePlanetIds",
    )
    if any(key not in selection_raw for key in required_keys):
        return None

    version = selection_raw.get("algorithmVersion")
    if not isinstance(version, int) or version < 1:
        raise ValidationError("homeworld layoutPriorSelection.algorithmVersion must be an int >= 1")
    fingerprint = _layout_prior_input_fingerprint_from_json(selection_raw.get("inputFingerprint"))

    evidence_lambda_raw = selection_raw.get("evidenceLambda")
    if not isinstance(evidence_lambda_raw, (int, float)) or isinstance(evidence_lambda_raw, bool):
        raise ValidationError("homeworld layoutPriorSelection.evidenceLambda must be a number")
    evidence_lambda = float(evidence_lambda_raw)
    if not (0.0 < evidence_lambda <= 1.0):
        raise ValidationError("homeworld layoutPriorSelection.evidenceLambda must be in (0, 1]")

    evidence_fingerprint = selection_raw.get("evidenceFingerprint")
    if not isinstance(evidence_fingerprint, str) or not evidence_fingerprint:
        raise ValidationError(
            "homeworld layoutPriorSelection.evidenceFingerprint must be a non-empty string"
        )

    ids_raw = selection_raw.get("mostProbablePlanetIds")
    if not isinstance(ids_raw, list) or not all(isinstance(item, int) for item in ids_raw):
        raise ValidationError(
            "homeworld layoutPriorSelection.mostProbablePlanetIds must be an int array"
        )
    return version, fingerprint, evidence_lambda, evidence_fingerprint, tuple(ids_raw)


def _ownership_provenance_to_json(provenance: OwnershipProvenance) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": provenance.kind,
        "turn": provenance.turn,
    }
    if provenance.ship_id is not None:
        payload["shipId"] = provenance.ship_id
    if provenance.planet_id is not None:
        payload["planetId"] = provenance.planet_id
    if provenance.radius_ly is not None:
        payload["radiusLy"] = provenance.radius_ly
    if provenance.distance_ly is not None:
        payload["distanceLy"] = provenance.distance_ly
    if provenance.age_source is not None:
        payload["ageSource"] = provenance.age_source
    return payload


def _ownership_provenance_from_json(data: dict[str, Any]) -> OwnershipProvenance:
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValidationError("homeworld ownership provenance kind must be a non-empty string")
    turn = data.get("turn")
    if not isinstance(turn, int) or turn < 1:
        raise ValidationError("homeworld ownership provenance turn must be an int >= 1")
    ship_id = data.get("shipId")
    if ship_id is not None and not isinstance(ship_id, int):
        raise ValidationError("homeworld ownership provenance shipId must be an int when present")
    planet_id = data.get("planetId")
    if planet_id is not None and not isinstance(planet_id, int):
        raise ValidationError("homeworld ownership provenance planetId must be an int when present")
    radius_ly = data.get("radiusLy")
    if radius_ly is not None and (
        isinstance(radius_ly, bool) or not isinstance(radius_ly, (int, float))
    ):
        raise ValidationError(
            "homeworld ownership provenance radiusLy must be a number when present"
        )
    distance_ly = data.get("distanceLy")
    if distance_ly is not None and (
        isinstance(distance_ly, bool) or not isinstance(distance_ly, (int, float))
    ):
        raise ValidationError(
            "homeworld ownership provenance distanceLy must be a number when present"
        )
    age_source = data.get("ageSource")
    if age_source is not None and (not isinstance(age_source, str) or not age_source):
        raise ValidationError(
            "homeworld ownership provenance ageSource must be a non-empty string when present"
        )
    return OwnershipProvenance(
        kind=kind,
        turn=turn,
        ship_id=ship_id,
        planet_id=planet_id,
        radius_ly=float(radius_ly) if radius_ly is not None else None,
        distance_ly=float(distance_ly) if distance_ly is not None else None,
        age_source=age_source,
    )


def _sector_owner_member_to_json(member: SectorOwnerMember) -> dict[str, Any]:
    return {
        "ownerSlot": member.owner_slot,
        "provenances": [_ownership_provenance_to_json(row) for row in member.provenances],
    }


def _sector_owner_member_from_json(data: dict[str, Any]) -> SectorOwnerMember:
    owner_slot = data.get("ownerSlot")
    if not isinstance(owner_slot, int) or owner_slot < 1:
        raise ValidationError("homeworld sector owner member ownerSlot must be an int >= 1")
    provenances_raw = data.get("provenances", [])
    if not isinstance(provenances_raw, list):
        raise ValidationError("homeworld sector owner member provenances must be a JSON array")
    provenances = tuple(
        _ownership_provenance_from_json(row) for row in provenances_raw if isinstance(row, dict)
    )
    if len(provenances) != len(provenances_raw):
        raise ValidationError("homeworld sector owner member provenances entries must be objects")
    return SectorOwnerMember(owner_slot=owner_slot, provenances=provenances)


def _sector_owner_sets_to_json(
    sector_owner_sets: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "sectorIndex": sector_index,
            "members": [_sector_owner_member_to_json(member) for member in members],
        }
        for sector_index, members in sector_owner_sets
    ]


def _sector_owner_sets_from_json(
    raw: object,
) -> tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError("homeworld evidence aggregate sectorOwnerSets must be a JSON array")
    rows: list[tuple[int, tuple[SectorOwnerMember, ...]]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValidationError("homeworld sectorOwnerSets entries must be objects")
        sector_index = entry.get("sectorIndex")
        if not isinstance(sector_index, int) or sector_index < 0:
            raise ValidationError("homeworld sectorOwnerSets.sectorIndex must be an int >= 0")
        members_raw = entry.get("members", [])
        if not isinstance(members_raw, list):
            raise ValidationError("homeworld sectorOwnerSets.members must be a JSON array")
        members = tuple(
            _sector_owner_member_from_json(row) for row in members_raw if isinstance(row, dict)
        )
        if len(members) != len(members_raw):
            raise ValidationError("homeworld sectorOwnerSets.members entries must be objects")
        rows.append((sector_index, members))
    return tuple(sorted(rows, key=lambda row: row[0]))


def _owner_possible_sectors_to_json(
    owner_possible_sectors: tuple[tuple[int, tuple[int, ...]], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "ownerSlot": owner_slot,
            "sectorIndexes": list(sector_indexes),
        }
        for owner_slot, sector_indexes in owner_possible_sectors
    ]


def _owner_possible_sectors_from_json(
    raw: object,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(
            "homeworld evidence aggregate ownerPossibleSectors must be a JSON array"
        )
    rows: list[tuple[int, tuple[int, ...]]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValidationError("homeworld ownerPossibleSectors entries must be objects")
        owner_slot = entry.get("ownerSlot")
        if not isinstance(owner_slot, int) or owner_slot < 1:
            raise ValidationError("homeworld ownerPossibleSectors.ownerSlot must be an int >= 1")
        indexes_raw = entry.get("sectorIndexes")
        if not isinstance(indexes_raw, list) or not all(
            isinstance(item, int) for item in indexes_raw
        ):
            raise ValidationError(
                "homeworld ownerPossibleSectors.sectorIndexes must be an int array"
            )
        rows.append((owner_slot, tuple(sorted(indexes_raw))))
    return tuple(sorted(rows, key=lambda row: row[0]))


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
    if aggregate.sector_owner_sets:
        payload["sectorOwnerSets"] = _sector_owner_sets_to_json(aggregate.sector_owner_sets)
    if aggregate.owner_possible_sectors:
        payload["ownerPossibleSectors"] = _owner_possible_sectors_to_json(
            aggregate.owner_possible_sectors
        )
    if aggregate.location_provenances:
        payload["locationProvenances"] = [
            _location_provenance_to_json(row) for row in aggregate.location_provenances
        ]
    if aggregate.evidence_algorithm_version > 0:
        payload["evidenceAlgorithmVersion"] = aggregate.evidence_algorithm_version
    if aggregate.layout_prior_algorithm_version is not None:
        payload["layoutPriorSelection"] = _layout_prior_selection_to_json(aggregate)
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
    selection_fingerprint: tuple[tuple[int, str, int | None], ...] = ()
    selection_evidence_lambda: float | None = None
    selection_evidence_fingerprint: str | None = None
    most_probable_ids: tuple[int, ...] = ()
    selection_raw = data.get("layoutPriorSelection")
    if selection_raw is not None:
        parsed_selection = _layout_prior_selection_from_json(selection_raw)
        if parsed_selection is not None:
            (
                selection_version,
                selection_fingerprint,
                selection_evidence_lambda,
                selection_evidence_fingerprint,
                most_probable_ids,
            ) = parsed_selection

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

    version_raw = data.get("evidenceAlgorithmVersion", 0)
    if isinstance(version_raw, bool) or not isinstance(version_raw, int) or version_raw < 0:
        raise ValidationError(
            "homeworld evidence aggregate evidenceAlgorithmVersion must be an int >= 0"
        )

    return HomeworldEvidenceAggregate(
        turn=turn,
        baseline_turn=baseline_turn,
        origin_distance_observations=observations,
        single_starbase_promotions=promotions,
        origin_distance_evidence_through_turn=through_turn,
        sector_owner_sets=_sector_owner_sets_from_json(data.get("sectorOwnerSets")),
        owner_possible_sectors=_owner_possible_sectors_from_json(data.get("ownerPossibleSectors")),
        location_provenances=_location_provenances_from_json(
            data.get("locationProvenances"),
            field_name="homeworld evidence aggregate locationProvenances",
        ),
        evidence_algorithm_version=version_raw,
        layout_prior_algorithm_version=selection_version,
        layout_prior_input_fingerprint=selection_fingerprint,
        layout_prior_evidence_lambda=selection_evidence_lambda,
        layout_prior_evidence_fingerprint=selection_evidence_fingerprint,
        most_probable_planet_ids=most_probable_ids,
    )
