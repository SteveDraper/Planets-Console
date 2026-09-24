"""Scoreboard-slice fleet wires match full-turn observation results."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.compute_plane.turn_delta import (
    advance_ledger_to_turn,
    apply_fleet_turn_delta_for_player,
)
from api.analytics.fleet.scoreboard_slice import fleet_scoreboard_slice_to_json
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
    persisted_fleet_ledger_from_json,
)
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord


def _observation_signature(ledger: FleetAcquisitionLedger) -> tuple:
    return (
        ledger.player_id,
        ledger.player_name,
        tuple(_record_signature(record) for record in ledger.records),
    )


def _record_signature(record: FleetShipRecord) -> tuple:
    return (
        record.disposition,
        record.fields,
        record.build_option_sets,
        record.display_default_option_set_index,
        tuple((event.kind, event.turn, event.source, event.payload) for event in record.events),
    )


def _ledger_from_slice(turn, player_id: int) -> FleetAcquisitionLedger:
    baseline = ensure_fleet_baseline_for_player(turn.game.id, turn.player.id, turn, player_id)
    result = run_fleet_observation_leg(
        {
            "gameId": turn.game.id,
            "perspective": turn.player.id,
            "playerId": player_id,
            "materializeTurn": turn.settings.turn,
            "turnWire": fleet_scoreboard_slice_to_json(turn),
            "priorLedgerWire": None,
            "baselineLedgerWire": fleet_acquisition_ledger_to_json(baseline),
            "provenanceWire": {
                "turnEvidenceAtN": False,
                "priorLedgerAtNMinus1": False,
            },
        }
    )
    assert result.payload is not None
    persisted = persisted_fleet_ledger_from_json(result.payload["persistedLedgerWire"])
    return persisted.ledger


def _ledger_from_full_turn(turn, player_id: int) -> FleetAcquisitionLedger:
    baseline = ensure_fleet_baseline_for_player(turn.game.id, turn.player.id, turn, player_id)
    ledger = advance_ledger_to_turn(baseline, turn)
    return apply_fleet_turn_delta_for_player(
        ledger,
        FleetTurnContext.from_turn(turn),
        game_id=turn.game.id,
        perspective=turn.player.id,
        inference_materialization=None,
    )


def _assert_slice_matches_full_turn(turn) -> None:
    player_id = next(score.ownerid for score in turn.scores if score.turn == turn.settings.turn)
    assert _observation_signature(_ledger_from_slice(turn, player_id)) == _observation_signature(
        _ledger_from_full_turn(turn, player_id)
    )


def test_scoreboard_slice_matches_full_turn_on_normal_and_first_reliable(sample_turn) -> None:
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

    _assert_slice_matches_full_turn(normal)
    _assert_slice_matches_full_turn(first_reliable)
