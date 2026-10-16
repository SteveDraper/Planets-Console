"""Counterparty fleet loader reads prior-turn active ships from fleet persistence."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.counterparty_ledger import counterparty_fleet_loader
from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetShipRecord,
    PersistedFleetLedger,
)
from api.analytics.options import TurnAnalyticsOptions
from api.storage.memory_asset import MemoryAssetBackend

GAME_ID = 7
PERSPECTIVE = 3
TURN_NUMBER = 4
PLAYER_ID = 11


def _query_context(services: FleetComputeServices | None) -> AnalyticQueryContext:
    export_services: dict[str, object] = {}
    if services is not None:
        export_services[ANALYTIC_ID] = services
    return AnalyticQueryContext(
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        ambient_turn=TURN_NUMBER,
        options=TurnAnalyticsOptions(),
        load_turn=lambda _turn: None,
        export_registry={},
        export_services=export_services,
    )


def _services(persistence: FleetSnapshotPersistenceService) -> FleetComputeServices:
    return FleetComputeServices(
        persistence=persistence,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        load_turn=lambda _turn: None,
    )


def test_loader_is_absent_without_context_turn_or_services() -> None:
    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    services = _services(persistence)
    assert (
        counterparty_fleet_loader(
            None,
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn_number=TURN_NUMBER,
        )
        is None
    )
    assert (
        counterparty_fleet_loader(
            _query_context(services),
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn_number=1,
        )
        is None
    )
    assert (
        counterparty_fleet_loader(
            _query_context(None),
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn_number=TURN_NUMBER,
        )
        is None
    )


def test_loader_returns_empty_when_no_ledger_and_only_active_records() -> None:
    persistence = FleetSnapshotPersistenceService(MemoryAssetBackend(initial={}))
    load = counterparty_fleet_loader(
        _query_context(_services(persistence)),
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn_number=TURN_NUMBER,
    )
    assert load is not None
    assert load(PLAYER_ID) == ()

    active = FleetShipRecord(record_id="active-ship")
    lost = FleetShipRecord(record_id="lost-ship", disposition="lost")
    traded = FleetShipRecord(record_id="traded-ship", disposition="traded")
    persistence.put_ledger(
        GAME_ID,
        PERSPECTIVE,
        TURN_NUMBER - 1,
        PLAYER_ID,
        PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(
                player_id=PLAYER_ID,
                records=[lost, active, traded],
            ),
        ),
    )

    loaded = load(PLAYER_ID)
    assert tuple(record.record_id for record in loaded) == ("active-ship",)
