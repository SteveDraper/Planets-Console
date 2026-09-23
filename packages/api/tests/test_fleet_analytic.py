"""Tests for Fleet turn analytic registration shell."""

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.compute_context import invoke_analytic_compute
from api.analytics.fleet import ANALYTIC_ID, compute_fleet, get_fleet
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.registry import TURN_ANALYTICS
from api.errors import ValidationError


def test_fleet_registered_in_turn_analytics():
    assert "fleet" in TURN_ANALYTICS


def test_fleet_compute_returns_players_with_observed_records(sample_turn):
    data = get_fleet(sample_turn)
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    koshling = next(player for player in players if player["playerId"] == 8)
    assert len(koshling["records"]) == 5
    assert koshling["records"][0]["events"][0]["kind"] == "sighting"
    for player in players:
        assert isinstance(player["playerId"], int)
        assert isinstance(player["playerName"], str)


def test_compute_fleet_requires_durable_snapshot(sample_turn, monkeypatch):
    def fail_chain(*_args, **_kwargs):
        raise AssertionError("REST compute_fleet must not rematerialize via snapshot chain")

    monkeypatch.setattr(
        "api.analytics.fleet.chain._materialize_fleet_snapshot_chain",
        fail_chain,
    )
    services = build_ephemeral_fleet_compute_services(sample_turn)
    with pytest.raises(ValidationError, match="fleet roster snapshot is not durable"):
        invoke_analytic_compute(
            compute_fleet,
            sample_turn,
            load_turn=services.load_turn,
            export_services={ANALYTIC_ID: services},
            game_id=services.game_id,
            perspective=services.perspective,
        )


def test_registry_dispatches_fleet(sample_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline
    from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger

    services = build_ephemeral_fleet_compute_services(sample_turn)
    baseline = ensure_fleet_baseline(services.game_id, services.perspective, sample_turn)
    for ledger in baseline.players:
        services.persistence.put_ledger(
            services.game_id,
            services.perspective,
            sample_turn.settings.turn,
            ledger.player_id,
            PersistedFleetLedger(
                ledger=ledger,
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
    data = get_turn_analytic(
        "fleet",
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=services.load_turn,
        export_services={ANALYTIC_ID: services},
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    assert data["analyticId"] == "fleet"
    assert len(data["players"]) == 4
    assert data["players"][0]["playerName"] == "koshling"
