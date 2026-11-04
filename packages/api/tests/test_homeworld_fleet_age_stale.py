"""Durable fleet-age stale marker for homeworld evidence satisfaction."""

from __future__ import annotations

import threading
from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics.compute_context import make_analytic_compute_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.ledger_persisted_event import FleetAgeIdentityChanged
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.homeworld_locator.constants import HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
from api.analytics.homeworld_locator.evidence_ensure import (
    ensure_evidence_floor_algorithm_current,
    evidence_refined_through_shell,
)
from api.analytics.homeworld_locator.exports import (
    ensure_homeworld_export,
    is_homeworld_export_ensure_satisfied,
)
from api.analytics.homeworld_locator.fleet_age_input import FleetAgeInputStamp
from api.analytics.homeworld_locator.fleet_age_refetch import (
    clear_fleet_age_refetch_notices,
    fleet_age_identity_changed_handler,
    fleet_age_refetch_notice,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.serialization import fleet_age_stale_marker_from_json
from api.analytics.homeworld_locator.types import FleetAgeStaleMarker, HomeworldEvidenceAggregate
from api.analytics.turn_roster import iter_turn_players
from api.errors import ValidationError
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_homeworld_evidence_refine import (
    _baseline_state,
    _candidate,
    _floor_aggregate,
    _load_turn,
)
from tests.test_homeworld_fleet_age_input import _ledger, _turn_ladder
from tests.test_homeworld_locator_core import _export_services, _services


@pytest.fixture(autouse=True)
def _clear_refetch_notices():
    clear_fleet_age_refetch_notices()
    yield
    clear_fleet_age_refetch_notices()


def _stamped_aggregate(turn: int) -> HomeworldEvidenceAggregate:
    return HomeworldEvidenceAggregate(
        turn=turn,
        baseline_turn=1,
        evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
        fleet_age_input_stamp=FleetAgeInputStamp(players=()),
    )


def _event(turn: int, *, player_id: int = 1) -> FleetAgeIdentityChanged:
    return FleetAgeIdentityChanged(game_id=7, perspective=1, turn=turn, player_id=player_id)


def test_marker_codec_rejects_non_ints() -> None:
    marker = FleetAgeStaleMarker(stale_from_turn=3, generation=2)
    restored = fleet_age_stale_marker_from_json(
        {"staleFromTurn": 3, "generation": 2},
    )
    assert restored == marker
    with pytest.raises(ValidationError):
        fleet_age_stale_marker_from_json({"staleFromTurn": True, "generation": 1})
    with pytest.raises(ValidationError):
        fleet_age_stale_marker_from_json({"staleFromTurn": 1, "generation": 0})


def test_identity_change_sets_durable_marker_and_skips_unchanged_saves() -> None:
    storage = MemoryAssetBackend(initial={})
    homeworld = HomeworldLocatorPersistenceService(storage)
    fleet = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    fleet.on_fleet_age_identity_changed = fleet_age_identity_changed_handler(homeworld)
    created = _ledger(1, 42, 7, final=False)
    fleet.put_ledger(7, 1, 4, 1, created)
    marker = homeworld.get_fleet_age_stale_marker(7, 1)
    assert marker == FleetAgeStaleMarker(stale_from_turn=4, generation=1)
    assert fleet_age_refetch_notice(7, 1, after_epoch=0).epoch == 1

    same_identity = replace(
        created,
        ledger=replace(created.ledger, records=list(created.ledger.records)),
    )
    fleet.put_ledger(7, 1, 4, 1, same_identity)
    assert homeworld.get_fleet_age_stale_marker(7, 1) == marker

    fleet.put_ledger(7, 1, 4, 1, _ledger(1, 42, 8, final=True))
    edited = homeworld.get_fleet_age_stale_marker(7, 1)
    assert edited == FleetAgeStaleMarker(stale_from_turn=4, generation=2)

    fleet.put_ledger(7, 1, 2, 1, _ledger(1, 9, 1, final=False))
    earlier = homeworld.get_fleet_age_stale_marker(7, 1)
    assert earlier == FleetAgeStaleMarker(stale_from_turn=2, generation=3)

    fleet.delete_ledger(7, 1, 2, 1)
    removed = homeworld.get_fleet_age_stale_marker(7, 1)
    assert removed == FleetAgeStaleMarker(stale_from_turn=2, generation=4)

    reloaded = HomeworldLocatorPersistenceService(storage)
    assert reloaded.get_fleet_age_stale_marker(7, 1) == removed


def test_satisfaction_reads_no_ledgers_and_does_not_walk_turns() -> None:
    storage = MemoryAssetBackend(initial={})
    persistence = HomeworldLocatorPersistenceService(storage)
    turns = _turn_ladder()
    load_calls: list[int] = []

    def load_turn(turn_number: int):
        load_calls.append(turn_number)
        return turns.get(turn_number)

    services = _services(persistence, turns)
    services = replace(services, load_turn=load_turn)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turns[1].settings, _candidate(10)),
        _stamped_aggregate(1),
    )
    for turn_number in range(2, 21):
        persistence.put_evidence_aggregate(628580, 1, _stamped_aggregate(turn_number))

    evidence_reads: list[int] = []
    original = persistence.get_evidence_aggregate

    def track_evidence(game_id: int, perspective: int, turn_number: int):
        evidence_reads.append(turn_number)
        return original(game_id, perspective, turn_number)

    persistence.get_evidence_aggregate = track_evidence  # type: ignore[method-assign]
    with patch.object(FleetSnapshotPersistenceService, "get_ledger") as get_ledger:
        assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=20)
        get_ledger.assert_not_called()
    assert load_calls == []
    assert evidence_reads == [20]

    evidence_reads.clear()
    persistence.record_fleet_age_identity_changed(
        FleetAgeIdentityChanged(game_id=628580, perspective=1, turn=8, player_id=1)
    )
    with patch.object(FleetSnapshotPersistenceService, "get_ledger") as get_ledger:
        assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=7)
        assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=8) is False
        assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=20) is False
        get_ledger.assert_not_called()
    assert evidence_reads == [7, 8, 20]
    assert load_calls == []


def test_export_satisfaction_does_not_read_ledgers() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    turns = _turn_ladder()
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turns[1].settings, _candidate(10)),
        _stamped_aggregate(1),
    )
    for turn_number in range(2, 6):
        persistence.put_evidence_aggregate(628580, 1, _stamped_aggregate(turn_number))
    export_services = _export_services(services, turns)
    ctx = make_analytic_compute_context(
        turns[4],
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
        game_id=628580,
        perspective=1,
    ).exports
    fleet = export_services["fleet"]
    with patch.object(
        fleet.persistence,
        "get_ledger",
        wraps=fleet.persistence.get_ledger,
    ) as get_ledger:
        assert is_homeworld_export_ensure_satisfied(
            ctx,
            ExportScope(game_id=628580, perspective=1, turn=4),
        )
        get_ledger.assert_not_called()


def test_marker_unsatisfies_from_changed_turn_and_rerefine_keeps_later_aggregate() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    turns = _turn_ladder()
    turn_five = replace(turns[4], settings=replace(turns[4].settings, turn=5))
    turns[5] = turn_five
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turns[1].settings, _candidate(10)),
        _floor_aggregate(),
    )
    export_services = _export_services(services, turns)
    fleet = export_services["fleet"]
    owner = next(iter(iter_turn_players(turns[1]))).id
    ctx = make_analytic_compute_context(
        turns[5],
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
        game_id=628580,
        perspective=1,
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=5))
    kept = persistence.get_evidence_aggregate(628580, 1, 5)
    assert kept is not None

    fleet.persistence.on_fleet_age_identity_changed = fleet_age_identity_changed_handler(
        persistence
    )
    fleet.persistence.delete_ledger(628580, 1, 3, owner)
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=2)
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=3) is False
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=5) is False

    shell_four = make_analytic_compute_context(
        turns[4],
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
        game_id=628580,
        perspective=1,
    ).exports
    assert ensure_homeworld_export(shell_four, ExportScope(game_id=628580, perspective=1, turn=4))
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=4)
    assert persistence.get_evidence_aggregate(628580, 1, 5) == kept
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=5) is False


def test_floor_rewrite_reads_baseline_stamps_only_when_marker_covers_it() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    turns = {1: replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))}
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turns[1].settings, _candidate(10)),
        _stamped_aggregate(1),
    )
    export_services = _export_services(services, turns)
    fleet = export_services["fleet"].persistence
    with patch.object(fleet, "get_ledger", wraps=fleet.get_ledger) as get_ledger:
        assert (
            ensure_evidence_floor_algorithm_current(
                services,
                baseline_turn=1,
                fleet_persistence=fleet,
            )
            is False
        )
        get_ledger.assert_not_called()

    persistence.record_fleet_age_identity_changed(
        FleetAgeIdentityChanged(game_id=628580, perspective=1, turn=1, player_id=1)
    )
    with patch.object(fleet, "get_ledger", wraps=fleet.get_ledger) as get_ledger:
        assert ensure_evidence_floor_algorithm_current(
            services,
            baseline_turn=1,
            fleet_persistence=fleet,
        )
        assert get_ledger.call_count > 0
        assert {call.args[2] for call in get_ledger.call_args_list} == {1}
    assert persistence.get_fleet_age_stale_marker(628580, 1) is None
    stored = persistence.get_evidence_aggregate(628580, 1, 1)
    assert stored is not None
    assert stored.fleet_age_input_stamp is not None


def test_advance_keeps_marker_when_generation_changes() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    persistence.record_fleet_age_identity_changed(_event(5))
    observed = persistence.get_fleet_age_stale_marker(7, 1)
    assert observed is not None
    persistence.record_fleet_age_identity_changed(_event(2, player_id=2))
    persistence.advance_fleet_age_stale_marker(7, 1, refined_turn=5, observed=observed)
    marker = persistence.get_fleet_age_stale_marker(7, 1)
    assert marker == FleetAgeStaleMarker(stale_from_turn=2, generation=2)


def test_advance_skips_gaps_and_stops_for_a_stored_aggregate() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_evidence_aggregate(7, 1, _stamped_aggregate(1))
    persistence.put_evidence_aggregate(7, 1, replace(_stamped_aggregate(1), turn=4))
    persistence.record_fleet_age_identity_changed(_event(2))
    observed = persistence.get_fleet_age_stale_marker(7, 1)
    persistence.advance_fleet_age_stale_marker(7, 1, refined_turn=4, observed=observed)
    assert persistence.get_fleet_age_stale_marker(7, 1) is None

    persistence.record_fleet_age_identity_changed(_event(2))
    persistence.put_evidence_aggregate(7, 1, replace(_stamped_aggregate(1), turn=3))
    observed = persistence.get_fleet_age_stale_marker(7, 1)
    persistence.advance_fleet_age_stale_marker(7, 1, refined_turn=4, observed=observed)
    assert persistence.get_fleet_age_stale_marker(7, 1) == FleetAgeStaleMarker(
        stale_from_turn=2,
        generation=1,
    )


def test_concurrent_save_during_refine_stays_marked() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    persistence.record_fleet_age_identity_changed(_event(4))
    observed = persistence.get_fleet_age_stale_marker(7, 1)
    assert observed is not None
    barrier = threading.Barrier(2)

    def save() -> None:
        barrier.wait(timeout=5)
        persistence.record_fleet_age_identity_changed(_event(4, player_id=2))

    def finish_refine() -> None:
        barrier.wait(timeout=5)
        persistence.advance_fleet_age_stale_marker(7, 1, refined_turn=4, observed=observed)

    threads = [threading.Thread(target=save), threading.Thread(target=finish_refine)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    marker = persistence.get_fleet_age_stale_marker(7, 1)
    assert marker is not None
    assert marker.covers(4)
