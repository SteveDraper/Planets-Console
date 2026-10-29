"""Observation leg passes the prior through and forces turn evidence off."""

from __future__ import annotations

from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetCountDiscrepancy,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)


def _run_observation_leg(
    turn,
    player_id: int,
    *,
    baseline: FleetAcquisitionLedger,
    prior: PersistedFleetLedger | None,
    prior_ledger_at_n_minus_1: bool,
) -> PersistedFleetLedger:
    job_wire = {
        "gameId": turn.game.id,
        "perspective": turn.player.id,
        "playerId": player_id,
        "materializeTurn": turn.settings.turn,
        "priorLedgerWire": (persisted_fleet_ledger_to_json(prior) if prior is not None else None),
        "baselineLedgerWire": fleet_acquisition_ledger_to_json(baseline),
        "provenanceWire": {
            "turnEvidenceAtN": True,
            "priorLedgerAtNMinus1": prior_ledger_at_n_minus_1,
        },
    }
    result = run_fleet_observation_leg(job_wire)
    assert result.payload is not None
    return persisted_fleet_ledger_from_json(result.payload["persistedLedgerWire"])


def test_observation_leg_returns_the_prior_and_forces_turn_evidence_off(sample_turn) -> None:
    player_id = next(
        score.ownerid for score in sample_turn.scores if score.turn == sample_turn.settings.turn
    )
    baseline = ensure_fleet_baseline_for_player(
        sample_turn.game.id,
        sample_turn.player.id,
        sample_turn,
        player_id,
    )
    persisted = _run_observation_leg(
        sample_turn,
        player_id,
        baseline=baseline,
        prior=None,
        prior_ledger_at_n_minus_1=False,
    )
    assert fleet_acquisition_ledger_to_json(persisted.ledger) == fleet_acquisition_ledger_to_json(
        baseline
    )
    assert persisted.provenance.turn_evidence_at_n is False
    assert persisted.provenance.prior_ledger_at_n_minus_1 is False

    prior_ledger = FleetAcquisitionLedger(
        player_id=player_id,
        player_name="prior-name",
        discrepancy=FleetCountDiscrepancy(
            host_turn=4,
            active_row_count=9,
            scoreboard_implied_count=1,
        ),
    )
    prior = PersistedFleetLedger(
        ledger=prior_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persisted = _run_observation_leg(
        sample_turn,
        player_id,
        baseline=baseline,
        prior=prior,
        prior_ledger_at_n_minus_1=True,
    )
    assert persisted.ledger.player_name == "prior-name"
    assert persisted.ledger.discrepancy == prior_ledger.discrepancy
    assert persisted.provenance.turn_evidence_at_n is False
    assert persisted.provenance.prior_ledger_at_n_minus_1 is True
