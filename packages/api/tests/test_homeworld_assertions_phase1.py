"""Homeworld assertion persistence and merge-above-read (#37 Phase 1)."""

from __future__ import annotations

import pytest
from api.analytics.homeworld_locator.assertions import (
    revoke_location_assertion,
    revoke_ownership_assertion,
    upsert_location_assertion,
    upsert_ownership_assertion,
)
from api.analytics.homeworld_locator.constants import (
    ATTRIBUTION_INFERRED,
    ATTRIBUTION_USER_ASSERTED,
)
from api.analytics.homeworld_locator.merge_above_read import (
    MergedHomeworldEvidence,
    merge_homeworld_evidence_above_read,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    PROVENANCE_ASSERTED,
    PROVENANCE_BASELINE_PROFILE,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    LocationProvenance,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.serialization import (
    homeworld_evidence_aggregate_from_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_from_json,
    homeworld_locator_game_state_to_json,
)
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
    ensure_candidates_for_asserted_locations,
)
from api.storage.memory_asset import MemoryAssetBackend


@pytest.fixture
def persistence() -> HomeworldLocatorPersistenceService:
    return HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))


def _empty_state(**kwargs) -> HomeworldLocatorGameState:
    defaults = {
        "candidates": (),
        "baseline_turn": 1,
        "baseline_degraded": False,
    }
    defaults.update(kwargs)
    return HomeworldLocatorGameState(**defaults)


def test_game_state_round_trips_asserted_provenances() -> None:
    state = _empty_state(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=10,
                perspective=1,
                confidence_tier=CONFIDENCE_DEFINITE,
            ),
            HomeworldCandidateRecord(
                planet_id=99,
                perspective=None,
                confidence_tier=CONFIDENCE_POSSIBLE,
            ),
        ),
        asserted_location_provenances=(
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=99),
        ),
        asserted_sector_ownership=(
            (
                2,
                (
                    SectorOwnerMember(
                        owner_slot=3,
                        provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
                    ),
                ),
            ),
        ),
        asserted_planet_ownership=(
            (
                88,
                (
                    SectorOwnerMember(
                        owner_slot=4,
                        provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=6),),
                    ),
                ),
            ),
        ),
    )
    restored = homeworld_locator_game_state_from_json(homeworld_locator_game_state_to_json(state))
    assert restored == state


def test_legacy_attribution_user_asserted_migrates_on_game_state_read() -> None:
    """Single read-path migration: attribution=user_asserted → asserted locations."""
    restored = homeworld_locator_game_state_from_json(
        {
            "candidates": [
                {
                    "planetId": 10,
                    "perspective": 1,
                    "confidenceTier": CONFIDENCE_DEFINITE,
                    "attribution": ATTRIBUTION_INFERRED,
                },
                {
                    "planetId": 20,
                    "perspective": 2,
                    "confidenceTier": CONFIDENCE_POSSIBLE,
                    "attribution": ATTRIBUTION_USER_ASSERTED,
                    "assertedCue": True,
                },
            ],
            "baselineTurn": 3,
            "baselineDegraded": False,
            "settingsFingerprint": [],
        }
    )
    assert restored.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=3, planet_id=20),
    )
    by_planet = {row.planet_id: row for row in restored.candidates}
    assert by_planet[10].attribution == ATTRIBUTION_INFERRED
    assert by_planet[10].asserted_cue is False
    assert by_planet[20].attribution == ATTRIBUTION_INFERRED
    assert by_planet[20].asserted_cue is False
    # Persisted payload must not re-store user_asserted / assertedCue as authority.
    payload = homeworld_locator_game_state_to_json(restored)
    assert "assertedLocationProvenances" in payload
    for row in payload["candidates"]:
        assert row["attribution"] == ATTRIBUTION_INFERRED
        assert "assertedCue" not in row


def test_evidence_aggregate_round_trips_location_provenances() -> None:
    aggregate = HomeworldEvidenceAggregate(
        turn=3,
        baseline_turn=1,
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
            LocationProvenance(
                kind="single_starbase_new_build",
                turn=3,
                planet_id=20,
            ),
        ),
    )
    restored = homeworld_evidence_aggregate_from_json(
        homeworld_evidence_aggregate_to_json(aggregate)
    )
    assert restored.location_provenances == aggregate.location_provenances


def test_merge_above_read_unions_asserted_and_machine_location() -> None:
    game_state = _empty_state(
        asserted_location_provenances=(
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
        ),
    )
    aggregate = HomeworldEvidenceAggregate(
        turn=5,
        baseline_turn=1,
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
        ),
        sector_owner_sets=(
            (
                1,
                (
                    SectorOwnerMember(
                        owner_slot=1,
                        provenances=(
                            OwnershipProvenance(
                                kind=PROVENANCE_NEARBY_PLANET_OWNERSHIP,
                                turn=2,
                                planet_id=50,
                                distance_ly=10.0,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    game_state = HomeworldLocatorGameState(
        candidates=game_state.candidates,
        baseline_turn=game_state.baseline_turn,
        baseline_degraded=game_state.baseline_degraded,
        asserted_location_provenances=game_state.asserted_location_provenances,
        asserted_sector_ownership=(
            (
                1,
                (
                    SectorOwnerMember(
                        owner_slot=2,
                        provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
                    ),
                ),
            ),
        ),
    )
    merged = merge_homeworld_evidence_above_read(game_state=game_state, aggregate=aggregate)
    assert isinstance(merged, MergedHomeworldEvidence)
    assert {row.planet_id for row in merged.location_provenances} == {10, 20}
    assert any(row.kind == PROVENANCE_ASSERTED for row in merged.location_provenances)
    sector_1 = dict(merged.sector_owner_sets)[1]
    slots = {member.owner_slot for member in sector_1}
    assert slots == {1, 2}


def test_location_assert_creates_candidate_when_missing() -> None:
    state = _empty_state(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=10,
                perspective=1,
                confidence_tier=CONFIDENCE_POSSIBLE,
            ),
        ),
    )
    updated = upsert_location_assertion(state, planet_id=99, turn=4)
    assert any(row.planet_id == 99 for row in updated.candidates)
    assert updated.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=4, planet_id=99),
    )
    # Re-assert replaces (no duplicate) at same planet.
    again = upsert_location_assertion(updated, planet_id=99, turn=7)
    assert again.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=7, planet_id=99),
    )


def test_ownership_assert_sector_keyed_when_sectors_exist() -> None:
    state = _empty_state()
    updated = upsert_ownership_assertion(
        state,
        owner_slot=3,
        turn=4,
        sector_index=2,
        planet_id=None,
        sectors_exist=True,
    )
    assert updated.asserted_sector_ownership == (
        (
            2,
            (
                SectorOwnerMember(
                    owner_slot=3,
                    provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=4),),
                ),
            ),
        ),
    )
    assert updated.asserted_planet_ownership == ()


def test_ownership_assert_planet_keyed_when_sectors_absent() -> None:
    state = _empty_state()
    updated = upsert_ownership_assertion(
        state,
        owner_slot=5,
        turn=4,
        sector_index=None,
        planet_id=42,
        sectors_exist=False,
    )
    assert updated.asserted_planet_ownership == (
        (
            42,
            (
                SectorOwnerMember(
                    owner_slot=5,
                    provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=4),),
                ),
            ),
        ),
    )
    assert updated.asserted_sector_ownership == ()


def test_ownership_assert_rejects_wrong_keying() -> None:
    state = _empty_state()
    with pytest.raises(ValueError, match="sector"):
        upsert_ownership_assertion(
            state,
            owner_slot=1,
            turn=1,
            sector_index=None,
            planet_id=10,
            sectors_exist=True,
        )
    with pytest.raises(ValueError, match="planet"):
        upsert_ownership_assertion(
            state,
            owner_slot=1,
            turn=1,
            sector_index=0,
            planet_id=None,
            sectors_exist=False,
        )


def test_revoke_removes_only_asserted_provenance() -> None:
    state = _empty_state(
        asserted_location_provenances=(
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=4, planet_id=10),
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=4, planet_id=20),
        ),
        asserted_sector_ownership=(
            (
                1,
                (
                    SectorOwnerMember(
                        owner_slot=2,
                        provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=4),),
                    ),
                ),
            ),
        ),
    )
    after_location = revoke_location_assertion(state, planet_id=10)
    assert after_location.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=4, planet_id=20),
    )
    after_owner = revoke_ownership_assertion(
        after_location,
        sector_index=1,
        planet_id=None,
        owner_slot=2,
        sectors_exist=True,
    )
    assert after_owner.asserted_sector_ownership == ()


def test_invalidate_preserves_asserted_provenances(persistence) -> None:
    persistence.put_game_state(
        628580,
        _empty_state(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=10,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                    attribution=ATTRIBUTION_INFERRED,
                ),
                HomeworldCandidateRecord(
                    planet_id=20,
                    perspective=None,
                    confidence_tier=CONFIDENCE_POSSIBLE,
                ),
            ),
            settings_fingerprint=(1, 2, 3),
            asserted_location_provenances=(
                LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
            ),
            asserted_sector_ownership=(
                (
                    0,
                    (
                        SectorOwnerMember(
                            owner_slot=9,
                            provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
                        ),
                    ),
                ),
            ),
        ),
    )
    retained = persistence.invalidate_inferred_game_state(628580)
    assert retained is not None
    assert retained.settings_fingerprint == ()
    # Inferred candidates cleared; asserted location ensures candidate shell remains.
    assert {row.planet_id for row in retained.candidates} == {20}
    assert retained.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
    )
    assert retained.asserted_sector_ownership[0][0] == 0
    assert persistence.get_game_state(628580) == retained


def test_clear_baseline_for_recompute_preserves_asserts(persistence) -> None:
    persistence.put_game_state(
        628580,
        _empty_state(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=10,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
            ),
            asserted_location_provenances=(
                LocationProvenance(kind=PROVENANCE_ASSERTED, turn=3, planet_id=55),
            ),
        ),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(
            turn=1,
            baseline_turn=1,
            location_provenances=(
                LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
            ),
        ),
    )
    persistence.clear_baseline_for_recompute(628580, 1)
    retained = persistence.get_game_state(628580)
    assert retained is not None
    assert retained.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=3, planet_id=55),
    )
    assert {row.planet_id for row in retained.candidates} == {55}
    assert persistence.get_evidence_aggregate(628580, 1, 1) is None


def test_ensure_candidates_for_asserted_locations() -> None:
    inferred = (
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=1,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    asserted = (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=2, planet_id=10),
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=2, planet_id=99),
    )
    merged = ensure_candidates_for_asserted_locations(
        inferred=inferred,
        asserted_location_provenances=asserted,
    )
    assert [row.planet_id for row in merged] == [10, 99]
    # Shells are not stamped with asserted_cue; cull protection uses durable keys.
    assert all(row.asserted_cue is False for row in merged)


def test_derive_candidates_sets_definite_and_asserted_cue() -> None:
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    candidates = (
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
        HomeworldCandidateRecord(
            planet_id=20,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    merged = MergedHomeworldEvidence(
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
        ),
        sector_owner_sets=(
            (
                0,
                (
                    SectorOwnerMember(
                        owner_slot=7,
                        provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
                    ),
                ),
            ),
        ),
        planet_owner_sets=(),
    )
    derived = derive_candidates_from_merged_evidence(
        candidates,
        merged,
        planet_sector_index={20: 0},
    )
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[20].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[20].asserted_cue is True
    assert by_planet[20].attribution == ATTRIBUTION_INFERRED
    assert by_planet[20].perspective == 7
    assert by_planet[10].confidence_tier == CONFIDENCE_POSSIBLE
    assert by_planet[10].asserted_cue is False
    assert by_planet[10].attribution == ATTRIBUTION_INFERRED


def test_derive_asserted_wins_over_machine_strong_despite_prior_definite() -> None:
    """Asserted location wins; machine-strong loser is not left definite via prior_tier."""
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    candidates = (
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
        HomeworldCandidateRecord(
            planet_id=20,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    merged = MergedHomeworldEvidence(
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
        ),
        sector_owner_sets=(),
        planet_owner_sets=(),
    )
    derived = derive_candidates_from_merged_evidence(candidates, merged)
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[20].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[20].asserted_cue is True
    assert by_planet[10].confidence_tier == CONFIDENCE_POSSIBLE
    assert by_planet[10].asserted_cue is False


def test_derive_does_not_keep_prior_definite_without_planet_provenance() -> None:
    """When the merged list is non-empty, prior_tier cannot keep a non-listed planet definite."""
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    candidates = (
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
        HomeworldCandidateRecord(
            planet_id=20,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    merged = MergedHomeworldEvidence(
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
        ),
        sector_owner_sets=(),
        planet_owner_sets=(),
    )
    derived = derive_candidates_from_merged_evidence(candidates, merged)
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[20].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[10].confidence_tier == CONFIDENCE_POSSIBLE


def test_derive_empty_location_list_keeps_prior_tier() -> None:
    """Empty merged location list intentionally falls back to candidate row tiers."""
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    candidates = (
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
        HomeworldCandidateRecord(
            planet_id=20,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    merged = MergedHomeworldEvidence(
        location_provenances=(),
        sector_owner_sets=(),
        planet_owner_sets=(),
    )
    derived = derive_candidates_from_merged_evidence(candidates, merged)
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[10].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[20].confidence_tier == CONFIDENCE_POSSIBLE
