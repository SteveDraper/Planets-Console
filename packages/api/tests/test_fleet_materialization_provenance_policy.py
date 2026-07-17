"""Unit tests for fleet materialization provenance policy edges."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.materialization_provenance import (
    resolve_fleet_materialization_provenance,
)
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.scores.export_services import ScoresExportContext

from tests.scores_exports_helpers import (
    GAME_ID,
    first_player_id,
    inference_solution,
    perspective,
    schedule_row_with_ladder,
)


def _turn_context() -> FleetTurnContext:
    turn = MagicMock()
    turn.scores = []
    turn.settings.acceleratedturns = 0
    return FleetTurnContext(turn=turn, max_ship_id_bound=100)


def _resolve(**overrides):
    defaults = {
        "materialize_turn": 2,
        "prior_persisted": None,
        "turn_context": _turn_context(),
        "player_id": 8,
        "game_id": 628580,
        "perspective": 1,
        "load_turn": lambda turn_number: MagicMock() if turn_number == 2 else None,
        "inference_materialization": MagicMock(),
    }
    defaults.update(overrides)
    return resolve_fleet_materialization_provenance(**defaults)


def test_non_final_prior_ledger_does_not_close_prior_leg():
    """Non-final provenance at N-1 leaves prior_ledger_at_n_minus_1 false."""
    prior_persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    assert prior_persisted.provenance.is_final is False

    with patch(
        "api.analytics.fleet.materialization_provenance._scores_turn_evidence_closed_for_player",
        return_value=True,
    ):
        provenance = _resolve(prior_persisted=prior_persisted)

    assert provenance.prior_ledger_at_n_minus_1 is False
    assert provenance.turn_evidence_at_n is True


def test_scheduler_row_run_does_not_close_turn_evidence(sample_turn):
    """In-progress scores RowRun is ensure-satisfied but must not close turnEvidenceAtN."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=12)],
    )
    scores_services = ScoresExportContext(scheduler=scheduler, persistence=None)
    turn_number = sample_turn.settings.turn
    perspective_id = perspective(sample_turn)

    def load_turn(stored_turn_number: int):
        return sample_turn if stored_turn_number == turn_number else None

    inference_materialization = FleetInferenceMaterialization(
        inference=FleetInferenceSupport(scores_services=scores_services),
        load_turn=load_turn,
    )
    turn_context = FleetTurnContext(turn=sample_turn, max_ship_id_bound=100)

    provenance = resolve_fleet_materialization_provenance(
        materialize_turn=turn_number,
        prior_persisted=None,
        turn_context=turn_context,
        player_id=player_id,
        game_id=GAME_ID,
        perspective=perspective_id,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert provenance.turn_evidence_at_n is False


def test_turn_one_prior_ledger_baseline_leg_is_true():
    provenance = _resolve(materialize_turn=1)

    assert provenance.prior_ledger_at_n_minus_1 is True


def test_missing_inference_materialization_closes_turn_evidence_at_turn_gt_one():
    provenance = _resolve(materialize_turn=2, inference_materialization=None)

    assert provenance.turn_evidence_at_n is False


def test_missing_rst_at_materialize_turn_closes_turn_evidence():
    provenance = _resolve(load_turn=lambda _turn_number: None)

    assert provenance.turn_evidence_at_n is False
