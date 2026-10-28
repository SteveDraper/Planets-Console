"""A scoreboard slice is enough to run the observation leg."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.scoreboard_slice import fleet_scoreboard_slice_to_json
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

from tests.fixtures.military_score_inference import with_score_owners_in_roster


def _run_observation_leg(
    turn,
    player_id: int,
    *,
    baseline: FleetAcquisitionLedger,
    prior: PersistedFleetLedger | None,
    prior_ledger_at_n_minus_1: bool,
):
    slice_wire = fleet_scoreboard_slice_to_json(turn)
    assert "planets" not in slice_wire
    result = run_fleet_observation_leg(
        {
            "gameId": turn.game.id,
            "perspective": turn.player.id,
            "playerId": player_id,
            "materializeTurn": turn.settings.turn,
            "turnWire": slice_wire,
            "priorLedgerWire": (
                persisted_fleet_ledger_to_json(prior) if prior is not None else None
            ),
            "baselineLedgerWire": fleet_acquisition_ledger_to_json(baseline),
            "provenanceWire": {
                "turnEvidenceAtN": True,
                "priorLedgerAtNMinus1": prior_ledger_at_n_minus_1,
            },
        }
    )
    assert result.payload is not None
    return persisted_fleet_ledger_from_json(result.payload["persistedLedgerWire"])


def _assert_slice_returns_baseline_unchanged(turn) -> None:
    player_id = next(score.ownerid for score in turn.scores if score.turn == turn.settings.turn)
    baseline = ensure_fleet_baseline_for_player(turn.game.id, turn.player.id, turn, player_id)
    persisted = _run_observation_leg(
        turn,
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


def test_scoreboard_slice_runs_observation_leg_without_copying_the_prior(sample_turn) -> None:
    normal = replace(sample_turn, settings=replace(sample_turn.settings, acceleratedturns=0))
    accelerated_turn = sample_turn.settings.acceleratedturns or 3
    current_scores = [
        replace(score, turn=accelerated_turn) if score.turn == sample_turn.settings.turn else score
        for score in sample_turn.scores
    ]
    first_reliable = replace(
        sample_turn,
        settings=replace(
            sample_turn.settings,
            turn=accelerated_turn,
            acceleratedturns=accelerated_turn,
        ),
        scores=current_scores,
    )

    assert normal.settings.acceleratedturns == 0
    assert first_reliable.settings.turn == first_reliable.settings.acceleratedturns
    assert sample_turn.planets
    assert "planets" not in fleet_scoreboard_slice_to_json(sample_turn)

    _assert_slice_returns_baseline_unchanged(normal)
    _assert_slice_returns_baseline_unchanged(first_reliable)

    opening_scores = [
        replace(score, turn=2) if score.turn == sample_turn.settings.turn else score
        for score in sample_turn.scores
    ]
    opening_reveal = with_score_owners_in_roster(
        replace(
            sample_turn,
            settings=replace(sample_turn.settings, turn=2, acceleratedturns=0),
            scores=opening_scores,
        )
    )
    _assert_slice_returns_baseline_unchanged(opening_reveal)

    player_id = next(score.ownerid for score in normal.scores if score.turn == normal.settings.turn)
    baseline = ensure_fleet_baseline_for_player(
        normal.game.id, normal.player.id, normal, player_id
    )
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
        normal,
        player_id,
        baseline=baseline,
        prior=prior,
        prior_ledger_at_n_minus_1=True,
    )
    assert persisted.ledger.player_name == "prior-name"
    assert persisted.ledger.discrepancy == prior_ledger.discrepancy
    assert persisted.provenance.turn_evidence_at_n is False
    assert persisted.provenance.prior_ledger_at_n_minus_1 is True
