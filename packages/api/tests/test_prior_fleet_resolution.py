"""Scores prior-fleet resolution: apply overlay only for ensure-final ledgers."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.prior_fleet_resolution import resolve_prior_fleet_for_scores
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs

from tests.export_chain_test_fixtures import GAME_ID, export_chain_query_context
from tests.fleet_chain_test_turns import HOST_TURN
from tests.fleet_exports_helpers import host_turn_at
from tests.scores_exports_helpers import first_player_id


def test_generation_stale_provenance_final_ledger_is_not_applied(sample_turn, persistence):
    """Readable provenance-(true, true) ledger with stale generation is not applied."""
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    ctx = export_chain_query_context(host_turn, persistence=persistence)
    player_id = first_player_id(host_turn)
    prior_turn = HOST_TURN - 1
    fleet_persistence = ctx.export_services["fleet"].persistence

    prior_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(GAME_ID, 1, host_turn, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    fleet_persistence.put_ledger(GAME_ID, 1, prior_turn, player_id, prior_persisted)
    assert fleet_persistence.has_final_ledger(GAME_ID, 1, prior_turn, player_id) is True

    fleet_persistence.invalidate_player_ledgers_from_turn(
        GAME_ID,
        1,
        prior_turn,
        player_id,
        durable=True,
    )
    readable = fleet_persistence.get_ledger(GAME_ID, 1, prior_turn, player_id)
    assert readable is not None
    assert readable.provenance.is_final is True
    assert fleet_persistence.has_final_ledger(GAME_ID, 1, prior_turn, player_id) is False

    resolution = resolve_prior_fleet_for_scores(
        ctx,
        game_id=GAME_ID,
        perspective=1,
        turn_number=HOST_TURN,
        player_id=player_id,
        turn=host_turn,
        overlay_ensure=False,
    )

    assert resolution.input_status != "applied"
    assert resolution.overlay is None


def test_missing_fleet_services_does_not_treat_provenance_final_as_ensure_final(sample_turn):
    """Without fleet services, provenance-final DepOutputs prior is not applied."""
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    player_id = first_player_id(host_turn)
    prior_turn_number = HOST_TURN - 1
    prior_turn = replace(
        host_turn,
        settings=replace(host_turn.settings, turn=prior_turn_number),
        game=replace(host_turn.game, turn=prior_turn_number),
    )
    stored = {
        HOST_TURN: host_turn,
        prior_turn_number: prior_turn,
    }

    def load_turn(turn_number: int):
        return stored.get(turn_number)

    ctx = make_analytic_query_context(
        host_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={},
        game_id=GAME_ID,
        perspective=1,
    )
    prior_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(GAME_ID, 1, host_turn, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    assert prior_persisted.provenance.is_final is True

    prior_fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=GAME_ID,
        perspective=1,
        turn=prior_turn_number,
        player_id=player_id,
    )
    outputs = DependencyOutputs()
    outputs.put(
        prior_fleet_scope,
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(prior_persisted)},
    )

    resolution = resolve_prior_fleet_for_scores(
        ctx,
        game_id=GAME_ID,
        perspective=1,
        turn_number=HOST_TURN,
        player_id=player_id,
        turn=host_turn,
        dependency_outputs=outputs,
        overlay_ensure=False,
    )

    assert resolution.input_status != "applied"
    assert resolution.overlay is None
    assert resolution.input_status == "unavailable"
