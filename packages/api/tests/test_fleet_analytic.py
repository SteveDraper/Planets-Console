"""Tests for Fleet turn analytic registration shell."""

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.compute_context import invoke_analytic_compute
from api.analytics.fleet import ANALYTIC_ID, compute_fleet
from api.analytics.fleet.chain import _materialize_fleet_snapshot_chain
from api.analytics.fleet.compute_services import (
    FleetComputeServices,
    build_ephemeral_fleet_compute_services,
)
from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.registry import TURN_ANALYTICS
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.turn_roster import iter_turn_players
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


def _seed_compute_fleet_context(
    sample_turn,
    persistence: InferenceRowPersistenceService,
) -> tuple[FleetComputeServices, ScoresExportContext]:
    """Seed closed scores through T and final fleet through T-1 for ensure+leaf."""
    scores_services = ScoresExportContext(persistence=persistence)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )
    roster_ids = [player.id for player in iter_turn_players(sample_turn)]
    for turn_number in range(1, sample_turn.settings.turn + 1):
        for player_id in roster_ids:
            persistence.put_row(
                services.game_id,
                services.perspective,
                turn_number,
                player_id,
                PersistedInferenceRow(
                    status=STATUS_EXACT,
                    summary="seed",
                    solution_count=0,
                    is_complete=True,
                    solutions=[],
                ),
            )
    prior_turn = services.load_turn(sample_turn.settings.turn - 1)
    assert prior_turn is not None
    _materialize_fleet_snapshot_chain(
        services.persistence,
        services.game_id,
        services.perspective,
        prior_turn,
        load_turn=services.load_turn,
        inference_materialization=services.inference_materialization,
    )
    return services, scores_services


def test_fleet_registered_in_turn_analytics():
    assert "fleet" in TURN_ANALYTICS


def test_fleet_compute_returns_players_with_observed_records(sample_turn, persistence):
    services, scores_services = _seed_compute_fleet_context(sample_turn, persistence)
    data = invoke_analytic_compute(
        compute_fleet,
        sample_turn,
        load_turn=services.load_turn,
        export_services={
            ANALYTIC_ID: services,
            SCORES_ANALYTIC_ID: scores_services,
        },
    )
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    koshling = next(player for player in players if player["playerId"] == 8)
    assert len(koshling["records"]) == 5
    assert koshling["records"][0]["events"][0]["kind"] == "sighting"
    for player in players:
        assert isinstance(player["playerId"], int)
        assert isinstance(player["playerName"], str)


def test_registry_dispatches_fleet(sample_turn, persistence):
    services, scores_services = _seed_compute_fleet_context(sample_turn, persistence)
    data = get_turn_analytic(
        "fleet",
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=services.load_turn,
        export_services={
            ANALYTIC_ID: services,
            SCORES_ANALYTIC_ID: scores_services,
        },
    )
    assert data["analyticId"] == "fleet"
    assert len(data["players"]) == 4
    assert data["players"][0]["playerName"] == "koshling"
