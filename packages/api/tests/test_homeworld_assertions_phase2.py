"""Homeworld assertion Core service + HTTP (#37 Phase 2)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.constants import (
    ANALYTIC_ID,
    ATTRIBUTION_USER_ASSERTED,
    HOMEWORLD_BASELINE_ALGORITHM_VERSION,
    HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    PROVENANCE_ASSERTED,
    PROVENANCE_BASELINE_PROFILE,
    LocationProvenance,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)
from api.concepts.homeworld_layout import homeworld_settings_fingerprint
from api.config import ApiConfig, set_config
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json
from api.services.homeworld_assertion_service import (
    HomeworldAssertionService,
    homeworld_sectors_exist,
)
from api.storage import clear_backend_cache, get_storage
from api.storage.memory_asset import MemoryAssetBackend
from fastapi.testclient import TestClient

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


@pytest.fixture
def persistence():
    return HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))


@pytest.fixture
def assertion_service(persistence, sample_turn):
    turns = {sample_turn.settings.turn: sample_turn}

    def load_turn(n: int):
        return turns.get(n)

    return HomeworldAssertionService(
        persistence=persistence,
        load_turn=load_turn,
        list_stored_turns=lambda: sorted(turns),
        game_id=628580,
        perspective=1,
    )


def _seed_minimal_state(
    persistence: HomeworldLocatorPersistenceService,
    turn_info: TurnInfo,
) -> None:
    turn = turn_info.settings.turn
    fingerprint = homeworld_settings_fingerprint(turn_info.settings)
    persistence.put_game_state(
        628580,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=1,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
            ),
            baseline_turn=turn,
            baseline_degraded=True,
            settings_fingerprint=fingerprint,
            baseline_algorithm_version=HOMEWORLD_BASELINE_ALGORITHM_VERSION,
            asserted_location_provenances=(),
        ),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(
            turn=turn,
            baseline_turn=turn,
            location_provenances=(
                LocationProvenance(
                    kind=PROVENANCE_BASELINE_PROFILE,
                    turn=turn,
                    planet_id=1,
                ),
            ),
            evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
        ),
    )


def test_sample_turn_does_not_have_homeworld_sectors(sample_turn) -> None:
    # Sample asset is circular+round but not epic/standard 11-player → planet-keyed.
    assert homeworld_sectors_exist(sample_turn) is False


def test_upsert_location_assertion_persists_and_ensures_candidate(
    assertion_service, persistence, sample_turn
) -> None:
    _seed_minimal_state(persistence, sample_turn)
    result = assertion_service.upsert_location_assertion(
        planet_id=3,
        turn_number=sample_turn.settings.turn,
    )
    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.asserted_location_provenances == (
        LocationProvenance(
            kind=PROVENANCE_ASSERTED,
            turn=sample_turn.settings.turn,
            planet_id=3,
        ),
    )
    assert any(row.planet_id == 3 for row in state.candidates)
    assert result["analyticId"] == ANALYTIC_ID
    asserted_rows = [row for row in result["rows"] if row["planetId"] == 3]
    assert len(asserted_rows) == 1
    assert asserted_rows[0]["assertedCue"] is True
    assert asserted_rows[0]["attribution"] == ATTRIBUTION_USER_ASSERTED
    markers = [m for m in result["markers"] if m["planetId"] == 3]
    assert markers[0]["assertedCue"] is True


def test_revoke_location_assertion_removes_assert_only(
    assertion_service, persistence, sample_turn
) -> None:
    turn = sample_turn.settings.turn
    _seed_minimal_state(persistence, sample_turn)
    assertion_service.upsert_location_assertion(planet_id=3, turn_number=turn)
    result = assertion_service.revoke_location_assertion(planet_id=3, turn_number=turn)
    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.asserted_location_provenances == ()
    # Machine candidate for planet 1 remains; asserted shell for 3 may remain as inferred.
    assert any(row["planetId"] == 1 for row in result["rows"])
    cue_rows = [row for row in result["rows"] if row.get("assertedCue")]
    assert cue_rows == []


def test_ownership_assert_planet_keyed_when_sectors_absent(
    assertion_service, persistence, sample_turn
) -> None:
    turn = sample_turn.settings.turn
    _seed_minimal_state(persistence, sample_turn)
    assertion_service.upsert_ownership_assertion(
        owner_slot=2,
        turn_number=turn,
        planet_id=1,
        sector_index=None,
    )
    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.asserted_sector_ownership == ()
    assert len(state.asserted_planet_ownership) == 1
    assert state.asserted_planet_ownership[0][0] == 1


def test_ownership_assert_rejects_sector_key_when_sectors_absent(
    assertion_service, persistence, sample_turn
) -> None:
    turn = sample_turn.settings.turn
    _seed_minimal_state(persistence, sample_turn)
    with pytest.raises(ValidationError, match="planet"):
        assertion_service.upsert_ownership_assertion(
            owner_slot=2,
            turn_number=turn,
            planet_id=None,
            sector_index=0,
        )


def test_location_assert_rejects_planetoid(assertion_service, persistence, sample_turn) -> None:
    turn_number = sample_turn.settings.turn
    planetoid = replace(sample_turn.planets[2], debrisdisk=1)
    planets = list(sample_turn.planets)
    planets[2] = planetoid
    mutated = replace(sample_turn, planets=planets)
    turns = {turn_number: mutated}
    service = HomeworldAssertionService(
        persistence=persistence,
        load_turn=lambda n: turns.get(n),
        list_stored_turns=lambda: sorted(turns),
        game_id=628580,
        perspective=1,
    )
    _seed_minimal_state(persistence, mutated)
    with pytest.raises(ValidationError, match="planetoid"):
        service.upsert_location_assertion(planet_id=planetoid.id, turn_number=turn_number)


def test_refresh_wipes_machine_state_preserves_asserts_and_rebuilds(
    persistence, sample_turn
) -> None:
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {1: turn_one}
    service = HomeworldAssertionService(
        persistence=persistence,
        load_turn=lambda n: turns.get(n),
        list_stored_turns=lambda: sorted(turns),
        game_id=628580,
        perspective=1,
    )
    fingerprint = homeworld_settings_fingerprint(turn_one.settings)
    # Seed asserts + machine evidence; refresh must keep asserts and rebuild via ensure.
    persistence.put_game_state(
        628580,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=1,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
                HomeworldCandidateRecord(
                    planet_id=99,
                    perspective=None,
                    confidence_tier=CONFIDENCE_POSSIBLE,
                ),
            ),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=fingerprint,
            baseline_algorithm_version=HOMEWORLD_BASELINE_ALGORITHM_VERSION,
            asserted_location_provenances=(
                LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=99),
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
                LocationProvenance(
                    kind=PROVENANCE_BASELINE_PROFILE,
                    turn=1,
                    planet_id=1,
                ),
            ),
            evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
        ),
    )
    result = service.refresh(turn_number=1)
    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=99),
    )
    assert result["analyticId"] == ANALYTIC_ID
    assert result["available"] is True
    asserted = [row for row in result["rows"] if row["planetId"] == 99]
    assert len(asserted) == 1
    assert asserted[0]["assertedCue"] is True


@pytest.fixture
def http_client(sample_turn):
    clear_backend_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    raw["settings"]["turn"] = 1
    storage.put("games/628580/1/turns/1", raw)
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    hw = HomeworldLocatorPersistenceService(storage)
    _seed_minimal_state(hw, turn_one)
    from api.app import app

    yield TestClient(app, raise_server_exceptions=False)
    clear_backend_cache()


def test_core_http_upsert_and_revoke_location(http_client) -> None:
    upsert = http_client.post(
        "/v1/games/628580/1/turns/1/analytics/homeworld-locator/assertions",
        json={"axis": "location", "action": "upsert", "planetId": 3},
    )
    assert upsert.status_code == 200, upsert.text
    body = upsert.json()
    assert any(row["planetId"] == 3 and row["assertedCue"] is True for row in body["rows"])

    revoke = http_client.post(
        "/v1/games/628580/1/turns/1/analytics/homeworld-locator/assertions",
        json={"axis": "location", "action": "revoke", "planetId": 3},
    )
    assert revoke.status_code == 200, revoke.text
    assert not any(row.get("assertedCue") for row in revoke.json()["rows"])


def test_core_http_refresh(http_client) -> None:
    upsert = http_client.post(
        "/v1/games/628580/1/turns/1/analytics/homeworld-locator/assertions",
        json={"axis": "location", "action": "upsert", "planetId": 2},
    )
    assert upsert.status_code == 200, upsert.text
    refresh = http_client.post(
        "/v1/games/628580/1/turns/1/analytics/homeworld-locator/refresh",
    )
    assert refresh.status_code == 200, refresh.text
    body = refresh.json()
    assert body["analyticId"] == ANALYTIC_ID
    asserted = [row for row in body["rows"] if row["planetId"] == 2]
    assert len(asserted) == 1
    assert asserted[0]["assertedCue"] is True
