"""Tests for homeworld locator Phase 2 Core wire-up."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.homeworld_locator.baseline_ensure import (
    ensure_homeworld_baseline,
    materialize_homeworld_candidate_view,
    needs_baseline_recompute,
    resolve_baseline_turn,
)
from api.analytics.homeworld_locator.compute import compute_homeworld_locator, get_homeworld_locator
from api.analytics.homeworld_locator.compute_services import build_ephemeral_homeworld_services
from api.analytics.homeworld_locator.constants import (
    ANALYTIC_ID,
    ATTRIBUTION_INFERRED,
    HOMEWORLD_BASELINE_ALGORITHM_VERSION,
)
from api.analytics.homeworld_locator.exports import (
    EXPORT_CATALOG,
    ensure_homeworld_export,
    is_homeworld_export_ensure_satisfied,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
)
from api.analytics.homeworld_locator.ownership_projection import (
    project_sector_owner_sets_with_location_pins,
    unique_projected_owner_slot,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.serialization import homeworld_locator_game_state_from_json
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
    ensure_candidates_for_asserted_locations,
)
from api.analytics.persistence_paths import (
    game_global_analytic_document_key,
    turn_scoped_analytic_document_key,
)
from api.analytics.turn_roster import iter_turn_players, race_id_by_owner_slot
from api.concepts.homeworld_layout import (
    HW_DISTRIBUTION_CIRCULAR,
    INACTIVE_REASON_NO_HOMEWORLD,
    INACTIVE_REASON_WANDERING_TRIBES,
    MAP_SHAPE_ROUND,
    homeworld_locator_inactive_reason,
    homeworld_settings_fingerprint,
    is_homeworld_locator_available,
)
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn() -> TurnInfo:
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


@pytest.fixture
def memory_backend():
    return MemoryAssetBackend(initial={})


@pytest.fixture
def persistence(memory_backend):
    return HomeworldLocatorPersistenceService(memory_backend)


def _services(
    persistence: HomeworldLocatorPersistenceService,
    turns: dict[int, TurnInfo],
    *,
    game_id: int = 628580,
    perspective: int = 1,
    game_info=None,
):
    return build_ephemeral_homeworld_services(
        persistence=persistence,
        game_id=game_id,
        perspective=perspective,
        load_turn=lambda n: turns.get(n),
        list_stored_turns=lambda: sorted(turns),
        game_info=game_info,
    )


def _final_fleet_ledger(player_id: int) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )


def _seed_fleet_final_ledgers(
    fleet_services,
    *,
    turns: dict[int, TurnInfo],
) -> None:
    for turn_number, turn in turns.items():
        for player in iter_turn_players(turn):
            fleet_services.persistence.put_ledger(
                fleet_services.game_id,
                fleet_services.perspective,
                turn_number,
                player.id,
                _final_fleet_ledger(player.id),
            )


def _export_services(
    services,
    turns: dict[int, TurnInfo],
) -> dict[str, object]:
    """Homeworld + fleet export services with final fleet ledgers for dependency walk."""
    shell_turn = turns[max(turns)]
    fleet_services = build_ephemeral_fleet_compute_services(
        shell_turn,
        game_id=services.game_id,
        perspective=services.perspective,
        stored_turns=turns,
    )
    _seed_fleet_final_ledgers(fleet_services, turns=turns)
    return {
        ANALYTIC_ID: services,
        "fleet": fleet_services,
    }


def _turn_ladder(turn_one: TurnInfo, shell_turn: TurnInfo) -> dict[int, TurnInfo]:
    """Stored turns from 1 through shell for self-chain export ensure tests."""
    shell_number = shell_turn.settings.turn
    turns = {1: turn_one}
    for turn_number in range(2, shell_number + 1):
        turns[turn_number] = replace(
            shell_turn,
            settings=replace(shell_turn.settings, turn=turn_number),
        )
    return turns


def test_path_helpers() -> None:
    assert game_global_analytic_document_key(628580, ANALYTIC_ID) == (
        "games/628580/analytics/homeworld-locator"
    )
    assert turn_scoped_analytic_document_key(628580, 1, 111, ANALYTIC_ID) == (
        "games/628580/1/turns/111/analytics/homeworld-locator"
    )


def test_availability_nohomeworld_and_wandering_tribes(sample_turn) -> None:
    assert is_homeworld_locator_available(sample_turn.settings) is True
    assert homeworld_locator_inactive_reason(sample_turn.settings) is None

    no_hw = replace(sample_turn.settings, nohomeworld=True)
    assert is_homeworld_locator_available(no_hw) is False
    assert homeworld_locator_inactive_reason(no_hw) == INACTIVE_REASON_NO_HOMEWORLD

    wt = replace(sample_turn.settings, wanderingtribescount=3)
    assert is_homeworld_locator_available(wt) is False
    assert homeworld_locator_inactive_reason(wt) == INACTIVE_REASON_WANDERING_TRIBES


def test_availability_scenario_override_recipes(sample_turn) -> None:
    from api.concepts.homeworld_layout import (
        HW_DISTRIBUTION_ONE_VS_CIRCLE,
        INACTIVE_REASON_SCENARIO_OVERRIDE,
    )

    ashes = replace(sample_turn.settings, hwdistribution=HW_DISTRIBUTION_ONE_VS_CIRCLE)
    assert is_homeworld_locator_available(ashes) is False
    assert homeworld_locator_inactive_reason(ashes) == INACTIVE_REASON_SCENARIO_OVERRIDE

    intermix = replace(sample_turn.settings, extraplanets=2, extraplanetsrandomloc=True)
    assert homeworld_locator_inactive_reason(intermix) == INACTIVE_REASON_SCENARIO_OVERRIDE

    disunited = replace(sample_turn.settings, extraplanets=2, extraplanetsrandomloc=False)
    assert homeworld_locator_inactive_reason(disunited) == INACTIVE_REASON_SCENARIO_OVERRIDE


def test_persistence_round_trip_ephemeral(persistence) -> None:
    state = HomeworldLocatorGameState(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=42,
                perspective=1,
                confidence_tier="definite",
                attribution=ATTRIBUTION_INFERRED,
            ),
        ),
        baseline_turn=1,
        baseline_degraded=False,
        settings_fingerprint=(1, 2, 3),
    )
    floor = HomeworldEvidenceAggregate(turn=1, baseline_turn=1)
    persistence.put_baseline(628580, 1, state, floor)

    loaded_state = persistence.get_game_state(628580)
    loaded_floor = persistence.get_evidence_aggregate(628580, 1, 1)
    assert loaded_state == state
    assert loaded_floor == floor
    assert persistence.has_baseline_floor(628580, 1) is True


def test_persistence_round_trip_file(tmp_path, sample_turn) -> None:
    backend = FileStorageBackend(tmp_path)
    persistence = HomeworldLocatorPersistenceService(backend)
    state = HomeworldLocatorGameState(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=7,
                perspective=None,
                confidence_tier="possible",
            ),
        ),
        baseline_turn=1,
        baseline_degraded=True,
        settings_fingerprint=(),
    )
    floor = HomeworldEvidenceAggregate(turn=1, baseline_turn=1)
    persistence.put_baseline(628580, 1, state, floor)

    reloaded = HomeworldLocatorPersistenceService(FileStorageBackend(tmp_path))
    assert reloaded.get_game_state(628580) == state
    assert reloaded.get_evidence_aggregate(628580, 1, 1) == floor


def test_game_state_from_json_rejects_non_dict_candidate() -> None:
    with pytest.raises(ValidationError, match="must be a JSON object"):
        homeworld_locator_game_state_from_json(
            {
                "candidates": ["not-an-object"],
                "baselineTurn": 1,
                "baselineDegraded": False,
                "settingsFingerprint": [],
            }
        )


def test_ensure_candidates_keeps_asserted_location_shells() -> None:
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_ASSERTED,
        LocationProvenance,
    )

    inferred = (
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier="definite",
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=2,
            perspective=None,
            confidence_tier="possible",
            attribution=ATTRIBUTION_INFERRED,
        ),
    )
    asserted = (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=2),
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=3),
    )
    merged = ensure_candidates_for_asserted_locations(
        inferred=inferred,
        asserted_location_provenances=asserted,
    )
    assert [row.planet_id for row in merged] == [1, 2, 3]
    by_planet = {row.planet_id: row for row in merged}
    assert by_planet[1].attribution == ATTRIBUTION_INFERRED
    assert by_planet[2].asserted_cue is False
    assert by_planet[3].asserted_cue is False
    assert by_planet[3].confidence_tier == "possible"


def test_invalidate_inferred_preserves_user_asserted(persistence) -> None:
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_ASSERTED,
        LocationProvenance,
    )

    persistence.put_game_state(
        628580,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=10,
                    perspective=1,
                    confidence_tier="definite",
                    attribution=ATTRIBUTION_INFERRED,
                ),
                HomeworldCandidateRecord(
                    planet_id=20,
                    perspective=2,
                    confidence_tier="possible",
                ),
            ),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=(1, 2, 3),
            asserted_location_provenances=(
                LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=20),
            ),
        ),
    )
    retained = persistence.invalidate_inferred_game_state(628580)
    assert retained is not None
    assert {row.planet_id for row in retained.candidates} == {20}
    assert retained.asserted_location_provenances == (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=20),
    )
    assert retained.settings_fingerprint == ()
    assert persistence.get_game_state(628580) == retained


def test_invalidate_evidence_from_turn(persistence) -> None:
    for turn_number in (1, 2, 3):
        persistence.put_evidence_aggregate(
            628580,
            1,
            HomeworldEvidenceAggregate(turn=turn_number, baseline_turn=1),
        )
    cleared = persistence.invalidate_evidence_from_turn(628580, 1, 2)
    assert cleared == [2, 3]
    assert persistence.get_evidence_aggregate(628580, 1, 1) is not None
    assert persistence.get_evidence_aggregate(628580, 1, 2) is None


def test_baseline_ensure_writes_floor_not_shell_aggregate(persistence, sample_turn) -> None:
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    # Pretend settings.turn is 1 for baseline identity; use as only stored turn.
    services = _services(persistence, {1: turn_one})
    result = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert result.recomputed is True
    assert result.game_state.baseline_turn == 1
    assert result.game_state.baseline_degraded is False
    assert persistence.has_baseline_floor(628580, 1) is True
    # No copy-forward: shell turn 111 aggregate absent when only floor at 1 exists.
    assert persistence.get_evidence_aggregate(628580, 1, 111) is None


def test_baseline_floor_pins_viewpoint_homeworld_ownership(persistence, sample_turn) -> None:
    """Turn-1 floor refine must mint preferred-candidate ownership for the viewpoint HW.

    Evidence refine is not a DAG node at the baseline turn, so overlay ``isPinned``
    would otherwise stay false despite a definite slot-anchored homeworld.
    """
    center = (2000.0, 2000.0)
    radius = 550.0
    template = sample_turn.planets[0]
    planets = []
    for index in range(11):
        angle = index * (2.0 * math.pi / 11)
        is_hw = index == 0
        planets.append(
            replace(
                template,
                id=index + 1,
                name=f"P{index + 1}",
                x=int(round(center[0] + radius * math.cos(angle))),
                y=int(round(center[1] + radius * math.sin(angle))),
                ownerid=1 if is_hw else 0,
                clans=25_000 if is_hw else 0,
                temp=50 if is_hw else 0,
                debrisdisk=0,
            )
        )
    players = [
        replace(sample_turn.player, id=slot, username=f"p{slot}", raceid=1) for slot in range(1, 12)
    ]
    starbase = replace(sample_turn.starbases[0], planetid=1)
    turn_one = replace(
        sample_turn,
        settings=replace(
            sample_turn.settings,
            turn=1,
            hwdistribution=HW_DISTRIBUTION_CIRCULAR,
            mapshape=MAP_SHAPE_ROUND,
            shiplimit=500,
            endturn=100,
            campaignmode=False,
            homeworldhasstarbase=True,
        ),
        player=players[0],
        players=players,
        planets=planets,
        ships=[],
        starbases=[starbase],
    )
    services = _services(persistence, {1: turn_one})
    result = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert result.recomputed is True
    definite = [row for row in result.game_state.candidates if row.planet_id == 1]
    assert len(definite) == 1
    assert definite[0].confidence_tier == CONFIDENCE_DEFINITE
    assert definite[0].perspective == 1

    floor = result.floor_aggregate
    preferred_slots = {
        member.owner_slot
        for _sector, members in floor.sector_owner_sets
        for member in members
        if any(
            provenance.kind == PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP
            and provenance.planet_id == 1
            for provenance in member.provenances
        )
    }
    assert preferred_slots == {1}

    projected = project_sector_owner_sets_with_location_pins(
        dict(floor.sector_owner_sets),
        candidate_planet_ids_by_sector=[[1] if index == 0 else [] for index in range(11)],
        location_definite_planet_ids=frozenset({1}),
        perspective_by_planet_id={1: 1},
        race_id_by_owner_slot=race_id_by_owner_slot(turn_one),
    )
    pinned = {
        sector_index: unique_projected_owner_slot(projection)
        for sector_index, projection in projected.items()
        if unique_projected_owner_slot(projection) is not None
    }
    assert 1 in pinned.values()


def test_baseline_degraded_when_turn_one_missing(persistence, sample_turn) -> None:
    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=111))
    services = _services(persistence, {111: late})
    turn_info, baseline_turn, degraded = resolve_baseline_turn(services)
    assert turn_info is late
    assert baseline_turn == 111
    assert degraded is True

    result = ensure_homeworld_baseline(services, shell_turn=late)
    assert result.game_state.baseline_degraded is True
    assert result.game_state.baseline_turn == 111


def test_baseline_auto_ensure_turn_one(persistence, sample_turn) -> None:
    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=111))
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    ensure_calls: list[int] = []

    def ensure_turn(turn_number: int) -> TurnInfo | None:
        ensure_calls.append(turn_number)
        return turn_one if turn_number == 1 else None

    services = _services(persistence, {111: late})
    result = ensure_homeworld_baseline(
        services,
        shell_turn=late,
        ensure_turn=ensure_turn,
    )
    assert ensure_calls == [1]
    assert result.game_state.baseline_turn == 1
    assert result.game_state.baseline_degraded is False


def test_turn_analytic_service_wires_ensure_turn_when_username_set(
    persistence, sample_turn, monkeypatch
) -> None:
    """Turn-load username credential installs ensure_turn on the query context only."""
    from api.analytics.homeworld_locator.constants import ANALYTIC_ID
    from api.services.turn_analytic_service import TurnAnalyticService

    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=111))
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    ensure_calls: list[tuple[int, str]] = []

    class _Turns:
        def get_turn_info(self, game_id, perspective, turn_number):
            assert (game_id, perspective, turn_number) == (628580, 1, 111)
            return late

        def list_stored_turn_numbers(self, game_id, perspective):
            return [111]

        def ensure_turn_loaded(self, game_id, perspective, turn_number, params, planets):
            ensure_calls.append((turn_number, params.username))
            assert planets is not None
            return turn_one

    class _FakePlanets:
        @staticmethod
        def from_config():
            return object()

    svc = TurnAnalyticService(
        _Turns(),  # type: ignore[arg-type]
        storage=persistence._storage,
        homeworld_persistence=persistence,
        planets_client_factory=_FakePlanets.from_config,
    )

    captured: dict[str, object] = {}

    def fake_dispatch_turn_analytic(analytic_id, ctx):
        captured["export_services"] = ctx.exports.export_services
        captured["ctx_ensure_turn"] = ctx.exports.ensure_turn
        return {"analyticId": analytic_id}

    monkeypatch.setattr(
        "api.services.turn_analytic_service.ensure_table_map_compute",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "api.services.turn_analytic_service.dispatch_turn_analytic",
        fake_dispatch_turn_analytic,
    )

    svc.get_turn_analytics(628580, 1, 111, ANALYTIC_ID, username="captain")
    homeworld = captured["export_services"][ANALYTIC_ID]
    assert not hasattr(homeworld, "ensure_turn")
    ctx_ensure_turn = captured["ctx_ensure_turn"]
    assert ctx_ensure_turn is not None
    ensured = ctx_ensure_turn(1)
    assert ensured is turn_one
    assert ensure_calls == [(1, "captain")]
    fleet = captured["export_services"]["fleet"]
    assert not hasattr(fleet, "ensure_turn")

    svc.get_turn_analytics(628580, 1, 111, ANALYTIC_ID, username="")
    assert captured["ctx_ensure_turn"] is None


def test_recompute_when_turn_one_appears_after_degraded(persistence, sample_turn) -> None:
    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=111))
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {111: late}
    services = _services(persistence, turns)
    first = ensure_homeworld_baseline(services, shell_turn=late)
    assert first.game_state.baseline_degraded is True

    turns[1] = turn_one
    second = ensure_homeworld_baseline(services, shell_turn=late)
    assert second.recomputed is True
    assert second.game_state.baseline_turn == 1
    assert second.game_state.baseline_degraded is False


def test_recompute_when_baseline_algorithm_version_mismatches(persistence, sample_turn) -> None:
    """Stale HOMEWORLD_BASELINE_ALGORITHM_VERSION must force baseline recompute."""
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {1: turn_one}
    services = _services(persistence, turns)
    first = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert first.recomputed is True
    assert first.game_state.baseline_algorithm_version == HOMEWORLD_BASELINE_ALGORITHM_VERSION

    fingerprint = homeworld_settings_fingerprint(turn_one.settings)
    assert needs_baseline_recompute(services, settings_fingerprint=fingerprint) is False
    second = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert second.recomputed is False

    # 0 is the pre-version sentinel on HomeworldLocatorGameState.
    stale = replace(first.game_state, baseline_algorithm_version=0)
    persistence.put_baseline(
        628580,
        1,
        stale,
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1),
    )
    assert needs_baseline_recompute(services, settings_fingerprint=fingerprint) is True
    third = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert third.recomputed is True
    assert third.game_state.baseline_algorithm_version == HOMEWORLD_BASELINE_ALGORITHM_VERSION


def test_export_ensure_unsatisfied_when_degraded_and_turn_one_present(
    persistence, sample_turn
) -> None:
    """Export/orchestrator is_satisfied must share needs_baseline_recompute."""
    from api.analytics.compute_context import make_analytic_compute_context

    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=111))
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {111: late}
    services = _services(persistence, turns)
    first = ensure_homeworld_baseline(services, shell_turn=late)
    assert first.game_state.baseline_degraded is True

    turns[1] = turn_one
    turns = _turn_ladder(turn_one, late)
    ctx = make_analytic_compute_context(
        late,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(_services(persistence, turns), turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ExportScope(game_id=628580, perspective=1, turn=111)
    assert is_homeworld_export_ensure_satisfied(ctx, scope) is False

    assert ensure_homeworld_export(ctx, scope) is True
    assert is_homeworld_export_ensure_satisfied(ctx, scope) is True
    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.baseline_turn == 1
    assert state.baseline_degraded is False


def test_export_ensure_requires_shell_evidence_aggregate(persistence, sample_turn) -> None:
    from api.analytics.compute_context import make_analytic_compute_context

    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = _turn_ladder(turn_one, sample_turn)
    services = _services(persistence, turns)
    ensure_homeworld_baseline(services, shell_turn=sample_turn)

    ctx = make_analytic_compute_context(
        sample_turn,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ExportScope(game_id=628580, perspective=1, turn=111)
    assert is_homeworld_export_ensure_satisfied(ctx, scope) is False
    assert ensure_homeworld_export(ctx, scope) is True
    assert persistence.get_evidence_aggregate(628580, 1, 111) is not None


def test_export_ensure_raises_when_shell_turn_not_stored(persistence, sample_turn) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.homeworld_locator.evidence_refine_timing_history import (
        clear_ensure_failure_reports,
        recent_ensure_failure_reports,
        reset_evidence_refine_report_history_for_tests,
    )

    reset_evidence_refine_report_history_for_tests()
    clear_ensure_failure_reports()
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    # Baseline exists so ensure is not already satisfied, but shell turn 111 is absent.
    services = _services(persistence, {1: turn_one})
    ensure_homeworld_baseline(services, shell_turn=turn_one)

    ctx = make_analytic_compute_context(
        turn_one,
        load_turn=lambda n: {1: turn_one}.get(n),
        export_services=_export_services(services, {1: turn_one}),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ExportScope(game_id=628580, perspective=1, turn=111)
    assert is_homeworld_export_ensure_satisfied(ctx, scope) is False
    with pytest.raises(ValidationError, match="turn 111 is not stored"):
        ensure_homeworld_export(ctx, scope)
    failures = recent_ensure_failure_reports(game_id=628580, perspective=1)
    assert len(failures) == 1
    assert failures[0].reason == "turn_not_stored"
    assert failures[0].missing_turn == 111
    clear_ensure_failure_reports()


def test_baseline_ensure_durable_perspective_uses_slot_not_player_id(
    persistence, sample_turn
) -> None:
    """Player.id may differ from shell perspective; durable candidates use the slot.

    When GameInfo is available, slot resolution goes through
    GameService.perspective_for_player_id rather than equality remap.
    """
    from api.serialization.game import game_info_from_json
    from api.services.game_service import GameService

    viewpoint_player_id = 99
    shell_perspective = 2
    game_id = 628580

    raw_info = json.loads((ASSETS_DIR / "game_info_sample.json").read_text(encoding="utf-8"))
    game_info = game_info_from_json(raw_info)
    # Slot 2 owns player id 99; other slots keep distinct ids.
    remapped_players = [
        replace(player, id=(viewpoint_player_id if index == shell_perspective - 1 else 10 + index))
        for index, player in enumerate(game_info.players)
    ]
    game_info = replace(game_info, players=remapped_players)
    assert (
        GameService.perspective_for_player_id(game_info, viewpoint_player_id, game_id)
        == shell_perspective
    )
    assert (
        GameService.player_id_for_perspective(game_info, shell_perspective, game_id)
        == viewpoint_player_id
    )

    settings = replace(
        sample_turn.settings,
        turn=1,
        homeworldhasstarbase=False,
        verycloseplanets=99,
        closeplanets=99,
    )
    hw = replace(
        sample_turn.planets[0],
        id=42,
        ownerid=viewpoint_player_id,
        clans=20_000,
        temp=50,
        debrisdisk=0,
    )
    other = replace(
        sample_turn.planets[1] if len(sample_turn.planets) > 1 else sample_turn.planets[0],
        id=43,
        ownerid=0,
        clans=0,
        temp=0,
        debrisdisk=0,
        x=hw.x + 500,
        y=hw.y,
    )
    viewpoint_player = replace(sample_turn.player, id=viewpoint_player_id, raceid=1)
    turn_one = replace(
        sample_turn,
        settings=settings,
        player=viewpoint_player,
        planets=[hw, other],
        starbases=[],
    )
    services = _services(
        persistence,
        {1: turn_one},
        perspective=shell_perspective,
        game_info=game_info,
    )
    result = ensure_homeworld_baseline(services, shell_turn=turn_one)
    assert result.recomputed is True
    anchored = [row for row in result.game_state.candidates if row.perspective is not None]
    assert len(anchored) == 1
    assert anchored[0].planet_id == 42
    assert anchored[0].perspective == shell_perspective
    assert anchored[0].perspective != viewpoint_player_id


def test_map_table_payload_smoke(persistence, sample_turn) -> None:
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = _turn_ladder(turn_one, sample_turn)
    services = _services(persistence, turns)
    payload = get_homeworld_locator(
        sample_turn,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    )
    assert payload["analyticId"] == ANALYTIC_ID
    assert payload["available"] is True
    assert payload["baselineTurn"] == 1
    assert payload["baselineDegraded"] is False
    assert isinstance(payload["markers"], list)
    assert isinstance(payload["rows"], list)
    assert payload["regionOverlays"] == []
    assert payload["markers"] == [
        {
            "planetId": row["planetId"],
            "perspective": row["perspective"],
            "confidenceTier": row["confidenceTier"],
            "attribution": row["attribution"],
            "assertedCue": row["assertedCue"],
            "isMostProbable": row["isMostProbable"],
        }
        for row in payload["rows"]
    ]


def test_inactive_map_table_payload(persistence, sample_turn) -> None:
    inactive_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, nohomeworld=True),
    )
    services = _services(persistence, {111: inactive_turn})
    payload = get_homeworld_locator(
        inactive_turn,
        export_services=_export_services(services, {111: inactive_turn}),
    )
    assert payload["available"] is False
    assert payload["inactiveReason"] == INACTIVE_REASON_NO_HOMEWORLD
    assert payload["markers"] == []
    assert payload["rows"] == []
    assert payload["regionOverlays"] == []
    assert persistence.get_game_state(628580) is None


def test_compute_homeworld_locator_does_not_call_export_ensure(
    persistence, sample_turn, monkeypatch
) -> None:
    from api.analytics.compute_context import invoke_analytic_compute

    def fail_ensure(*_args, **_kwargs):
        raise AssertionError("REST compute_homeworld_locator must not call export ensure")

    monkeypatch.setattr(
        "api.analytics.homeworld_locator.exports.ensure_homeworld_export",
        fail_ensure,
    )
    turns = {111: sample_turn}
    services = _services(persistence, turns)
    with pytest.raises(ValidationError, match="game-global state missing after ensure"):
        invoke_analytic_compute(
            compute_homeworld_locator,
            sample_turn,
            load_turn=lambda n: turns.get(n),
            export_services=_export_services(services, turns),
            game_id=services.game_id,
            perspective=services.perspective,
        )


def test_candidate_view_materialize(persistence, sample_turn) -> None:
    from api.analytics.compute_context import make_analytic_compute_context

    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = _turn_ladder(turn_one, sample_turn)
    services = _services(persistence, turns)
    ctx = make_analytic_compute_context(
        sample_turn,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    view = materialize_homeworld_candidate_view(ctx, shell_turn=sample_turn)
    assert view.available is True
    assert view.baseline_turn == 1


def test_export_catalog_declares_self_chain() -> None:
    from api.analytics.export_types import EnsureDependency

    assert EXPORT_CATALOG.analytic_id == ANALYTIC_ID
    assert EXPORT_CATALOG.ensure_dependencies == (
        EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
        EnsureDependency(analytic_id="fleet", turn_delta=0, player_id="all", quality="final"),
    )


def test_registration_in_catalog() -> None:
    from api.analytics.catalog import catalog_entry
    from api.analytics.registry import TURN_ANALYTICS
    from api.compute.registry import COMPUTE_REGISTRY

    entry = catalog_entry(ANALYTIC_ID)
    assert entry.supports_table is False
    assert entry.supports_map is True
    assert ANALYTIC_ID in TURN_ANALYTICS
    assert ANALYTIC_ID in COMPUTE_REGISTRY


def test_run_homeworld_baseline_persist_round_trip(persistence, sample_turn) -> None:
    """Step computes wires without writing; PersistencePolicy.persist writes only."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.homeworld_locator.compute_orchestration import (
        HomeworldLocatorPersistencePolicy,
        build_homeworld_baseline_job_wire,
        run_homeworld_baseline,
    )
    from api.compute.scope import ComputeScope
    from api.compute.wire import DependencyOutputs

    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {1: turn_one, 111: sample_turn}
    services = _services(persistence, turns)
    ctx = make_analytic_compute_context(
        sample_turn,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=111,
    )

    job_wire = build_homeworld_baseline_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    result = run_homeworld_baseline(job_wire)

    assert result.outcome == "persist"
    assert result.persist_then_continue is True
    assert isinstance(result.payload, dict)
    assert result.payload.get("available") is True
    assert result.payload.get("recomputed") is True
    assert isinstance(result.payload.get("gameState"), dict)
    assert isinstance(result.payload.get("floorAggregate"), dict)
    assert "runBaselineEnsure" not in result.payload
    # Step must not durable-write; persist owns put_baseline after epoch checks.
    assert persistence.get_game_state(628580) is None
    assert persistence.has_baseline_floor(628580, 1) is False

    HomeworldLocatorPersistencePolicy().persist(ctx, scope, result.payload)

    assert persistence.has_baseline_floor(628580, 1) is True
    stored = persistence.get_game_state(628580)
    assert stored is not None
    assert stored.baseline_turn == 1
    assert stored.baseline_degraded is False


def test_baseline_persist_recompute_clears_shell_evidence(persistence, sample_turn) -> None:
    """Orchestrator baseline recompute must invalidate like ensure_homeworld_baseline."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.homeworld_locator.compute_orchestration import (
        HomeworldLocatorPersistencePolicy,
        build_homeworld_baseline_job_wire,
        build_homeworld_refine_job_wire,
        run_homeworld_baseline,
        run_homeworld_refine,
    )
    from api.compute.scope import ComputeScope
    from api.compute.wire import DependencyOutputs

    late = replace(sample_turn, settings=replace(sample_turn.settings, turn=2))
    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = {2: late}
    services = _services(persistence, turns)
    first = ensure_homeworld_baseline(services, shell_turn=late)
    assert first.game_state.baseline_degraded is True
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(
            turn=2,
            baseline_turn=2,
        ),
    )
    assert persistence.get_evidence_aggregate(628580, 1, 2) is not None

    turns[1] = turn_one
    services = _services(persistence, turns)
    ctx = make_analytic_compute_context(
        late,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
    )
    job_wire = build_homeworld_baseline_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    result = run_homeworld_baseline(job_wire)
    assert result.payload.get("recomputed") is True

    HomeworldLocatorPersistencePolicy().persist(ctx, scope, result.payload)

    state = persistence.get_game_state(628580)
    assert state is not None
    assert state.baseline_turn == 1
    assert state.baseline_degraded is False
    assert persistence.get_evidence_aggregate(628580, 1, 2) is None
    assert persistence.has_baseline_floor(628580, 1) is True

    # Floor at T1 is the prior; single-step refine at T2 can continue cleanly.
    refine_wire = build_homeworld_refine_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    refine_result = run_homeworld_refine(refine_wire)
    assert refine_result.outcome == "persist"
    HomeworldLocatorPersistencePolicy().persist(ctx, scope, refine_result.payload)
    shell = persistence.get_evidence_aggregate(628580, 1, 2)
    assert shell is not None
    assert shell.baseline_turn == 1
    assert shell.turn == 2


def test_baseline_persist_without_recompute_keeps_shell_evidence(persistence, sample_turn) -> None:
    """Evidence-only orchestrator entry must not wipe the refine chain."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.homeworld_locator.compute_orchestration import (
        HomeworldLocatorPersistencePolicy,
        build_homeworld_baseline_job_wire,
        run_homeworld_baseline,
    )
    from api.compute.scope import ComputeScope
    from api.compute.wire import DependencyOutputs

    turn_one = replace(sample_turn, settings=replace(sample_turn.settings, turn=1))
    turns = _turn_ladder(turn_one, sample_turn)
    services = _services(persistence, turns)
    ensure_homeworld_baseline(services, shell_turn=sample_turn)
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(turn=111, baseline_turn=1),
    )

    ctx = make_analytic_compute_context(
        sample_turn,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=111,
    )
    job_wire = build_homeworld_baseline_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    result = run_homeworld_baseline(job_wire)
    assert result.payload.get("recomputed") is False

    HomeworldLocatorPersistencePolicy().persist(ctx, scope, result.payload)

    assert persistence.get_evidence_aggregate(628580, 1, 111) is not None
    assert persistence.has_baseline_floor(628580, 1) is True


def test_run_homeworld_baseline_inactive_completes_without_persist(
    persistence, sample_turn
) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.homeworld_locator.compute_orchestration import (
        HomeworldLocatorPersistencePolicy,
        build_homeworld_baseline_job_wire,
        run_homeworld_baseline,
    )
    from api.compute.scope import ComputeScope
    from api.compute.wire import DependencyOutputs

    inactive = replace(sample_turn, settings=replace(sample_turn.settings, nohomeworld=True))
    services = _services(persistence, {111: inactive})
    ctx = make_analytic_compute_context(
        inactive,
        load_turn=lambda n: {111: inactive}.get(n),
        export_services=_export_services(services, {111: inactive}),
        game_id=services.game_id,
        perspective=services.perspective,
    ).exports
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=111,
    )
    job_wire = build_homeworld_baseline_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    result = run_homeworld_baseline(job_wire)
    assert result.outcome == "complete"
    assert result.payload == {"available": False}

    HomeworldLocatorPersistencePolicy().persist(ctx, scope, result.payload)
    assert persistence.get_game_state(628580) is None
