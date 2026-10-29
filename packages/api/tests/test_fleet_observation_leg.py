"""Observation leg carries no ledger. Persist folds the prior."""

from __future__ import annotations

from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg


def test_observation_leg_does_not_carry_a_ledger(sample_turn) -> None:
    job_wire = {
        "gameId": sample_turn.game.id,
        "perspective": sample_turn.player.id,
        "playerId": 1,
        "materializeTurn": sample_turn.settings.turn,
        "priorLedgerWire": {"ledger": {"playerId": 1, "records": [{"recordId": "frozen"}]}},
        "baselineLedgerWire": {"playerId": 1, "records": []},
        "provenanceWire": {
            "turnEvidenceAtN": True,
            "priorLedgerAtNMinus1": True,
        },
    }
    result = run_fleet_observation_leg(job_wire)
    assert result.outcome == "persist"
    assert result.persist_then_continue is True
    assert result.payload == {
        "materializeTurn": sample_turn.settings.turn,
        "fleetPersistLeg": "observation",
    }


def test_eliminated_observation_leg_is_flag_only() -> None:
    result = run_fleet_observation_leg(
        {
            "playerId": 4,
            "materializeTurn": 6,
            "eliminatedAtTurn": True,
        }
    )
    assert result.payload == {
        "materializeTurn": 6,
        "fleetPersistLeg": "observation",
        "eliminatedAtTurn": True,
    }
