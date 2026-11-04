"""On-disk fleet ages for homeworld refine, without a fleet ensure edge."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.evidence_ensure import evidence_refined_through_shell
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG, ensure_homeworld_export
from api.analytics.homeworld_locator.fleet_age_input import (
    merged_built_turns,
    read_fleet_age_input_stamp,
)
from api.analytics.homeworld_locator.fleet_age_refetch import (
    fleet_age_identity_changed_handler,
)
from api.analytics.homeworld_locator.models import PROVENANCE_ASSERTED, LocationProvenance
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.turn_roster import iter_turn_players
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_homeworld_evidence_refine import (
    _baseline_state,
    _candidate,
    _floor_aggregate,
    _load_turn,
)
from tests.test_homeworld_locator_core import _export_services, _services


def _ledger(player_id: int, ship_id: int, built_turn: int, *, final: bool) -> PersistedFleetLedger:
    provenance = (
        FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        )
        if final
        else FleetMaterializationProvenance()
    )
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            records=[
                FleetShipRecord(
                    record_id=f"rec-{ship_id}",
                    fields=FleetShipRecordFields(
                        ship_id=FleetFieldKnown(ship_id),
                        built_turn=FleetFieldKnown(built_turn),
                    ),
                )
            ],
        ),
        provenance=provenance,
    )


def _turn_ladder():
    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turns = {
        number: replace(turn_one, settings=replace(turn_one.settings, turn=number))
        for number in range(1, 5)
    }
    return turns


def test_catalog_does_not_ensure_fleet() -> None:
    assert all(dep.analytic_id != "fleet" for dep in EXPORT_CATALOG.ensure_dependencies)
    assert EXPORT_CATALOG.ensure_dependencies == (
        EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
    )


def test_read_includes_approximate_generation_behind_and_missing_files() -> None:
    turns = _turn_ladder()
    turn = turns[2]
    players = [player.id for player in iter_turn_players(turn)]
    assert len(players) >= 3
    present, behind, missing = players[0], players[1], players[2]
    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_ledger(628580, 1, 2, present, _ledger(present, 42, 7, final=False))
    persistence.put_ledger(628580, 1, 2, behind, _ledger(behind, 43, 4, final=True))
    persistence.invalidate_player_ledgers_from_turn(628580, 1, 2, behind, durable=True)

    assert persistence.has_final_ledger(628580, 1, 2, present) is False
    assert persistence.has_final_ledger(628580, 1, 2, behind) is False

    stamp = read_fleet_age_input_stamp(persistence, game_id=628580, perspective=1, turn=turn)
    by_player = {player.player_id: player for player in stamp.players}
    assert by_player[present].missing is False
    assert by_player[present].built_turns == ((42, 7),)
    assert by_player[behind].missing is False
    assert by_player[behind].built_turns == ((43, 4),)
    assert by_player[missing].missing is True
    assert by_player[missing].built_turns == ()
    assert merged_built_turns(stamp) == {42: 7, 43: 4}
    assert missing not in merged_built_turns(stamp)


def test_unchanged_build_turn_identity_does_not_bump_epoch_or_ensure() -> None:
    homeworld = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    persistence.on_fleet_age_identity_changed = fleet_age_identity_changed_handler(homeworld)
    first = _ledger(1, 42, 7, final=False)
    persistence.put_ledger(9, 1, 3, 1, first)
    assert homeworld.fleet_age_refetch_notice(9, 1, after_epoch=0).epoch == 1

    edited = replace(
        first,
        ledger=replace(first.ledger, records=list(first.ledger.records)),
    )
    with (
        patch("api.compute.export_ensure.ensure_export_scope_via_orchestrator") as ensure,
        patch("api.analytics.fleet.compute_orchestration.wake_fleet_scope") as wake,
    ):
        persistence.put_ledger(9, 1, 3, 1, edited)
        persistence.delete_ledger(9, 1, 4, 1)
        ensure.assert_not_called()
        wake.assert_not_called()
    assert homeworld.fleet_age_refetch_notice(9, 1, after_epoch=0).epoch == 1
    assert homeworld.fleet_age_refetch_notice(9, 1, after_epoch=1).from_turn is None


def test_create_edit_and_delete_bump_epoch_without_starting_work() -> None:
    homeworld = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    persistence.on_fleet_age_identity_changed = fleet_age_identity_changed_handler(homeworld)
    with (
        patch("api.compute.export_ensure.ensure_export_scope_via_orchestrator") as ensure,
        patch("api.analytics.fleet.compute_orchestration.wake_fleet_scope") as wake,
    ):
        persistence.put_ledger(9, 1, 2, 1, _ledger(1, 42, 7, final=False))
        persistence.put_ledger(9, 1, 2, 1, _ledger(1, 42, 8, final=True))
        persistence.delete_ledger(9, 1, 2, 1)
        ensure.assert_not_called()
        wake.assert_not_called()
    notice = homeworld.fleet_age_refetch_notice(9, 1, after_epoch=0)
    assert notice.epoch == 3
    assert notice.from_turn == 2
    assert homeworld.fleet_age_refetch_notice(9, 1, after_epoch=3).from_turn is None


def test_stamp_mismatch_rerefines_from_that_turn_and_keeps_later_aggregate() -> None:
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    from api.analytics.compute_context import make_analytic_compute_context

    turns = _turn_ladder()
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
    for turn_number in turns:
        fleet.persistence.put_ledger(
            628580,
            1,
            turn_number,
            owner,
            _ledger(owner, 42, 7, final=False),
        )
    ctx = make_analytic_compute_context(
        turns[4],
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
        game_id=628580,
        perspective=1,
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=4))
    assert evidence_refined_through_shell(
        services,
        baseline_turn=1,
        shell_turn=4,
    )

    state = persistence.get_game_state(628580)
    assert state is not None
    asserted = LocationProvenance(kind=PROVENANCE_ASSERTED, turn=1, planet_id=10)
    persistence.put_game_state(
        628580,
        replace(state, asserted_location_provenances=(asserted,)),
    )
    fleet.persistence.on_fleet_age_identity_changed = fleet_age_identity_changed_handler(
        persistence
    )
    fleet.persistence.put_ledger(
        628580,
        1,
        2,
        owner,
        _ledger(owner, 42, 9, final=False),
    )
    with patch.object(
        fleet.persistence,
        "get_ledger",
        wraps=fleet.persistence.get_ledger,
    ) as get_ledger:
        assert (
            evidence_refined_through_shell(
                services,
                baseline_turn=1,
                shell_turn=2,
            )
            is False
        )
        assert evidence_refined_through_shell(
            services,
            baseline_turn=1,
            shell_turn=1,
        )
        get_ledger.assert_not_called()
    kept = persistence.get_evidence_aggregate(628580, 1, 4)
    assert kept is not None

    shell_three = make_analytic_compute_context(
        turns[3],
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
        game_id=628580,
        perspective=1,
    ).exports
    assert ensure_homeworld_export(shell_three, ExportScope(game_id=628580, perspective=1, turn=3))
    assert evidence_refined_through_shell(
        services,
        baseline_turn=1,
        shell_turn=3,
    )
    assert persistence.get_evidence_aggregate(628580, 1, 4) == kept
    assert (
        evidence_refined_through_shell(
            services,
            baseline_turn=1,
            shell_turn=4,
        )
        is False
    )
    stored_state = persistence.get_game_state(628580)
    assert stored_state is not None
    assert stored_state.asserted_location_provenances == (asserted,)
    turn_two = persistence.get_evidence_aggregate(628580, 1, 2)
    assert turn_two is not None
    assert turn_two.fleet_age_input_stamp is not None
    assert merged_built_turns(turn_two.fleet_age_input_stamp)[42] == 9
