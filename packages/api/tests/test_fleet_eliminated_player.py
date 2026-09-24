"""Eliminated players persist an empty final fleet ledger (#528)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics.export_dependency_walk import walk_dependency_tree
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.fleet_table_player_run import wire_materialized_complete_event
from api.analytics.fleet.serialization import (
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord, PersistedFleetLedger
from api.compute.dag import plan_compute_dag
from api.compute.registry import COMPUTE_REGISTRY
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.errors import FleetScoresEvidenceOpenError

from tests.export_chain_test_fixtures import GAME_ID, export_chain_query_context
from tests.scores_exports_helpers import first_player_id, perspective

_FLEET = "fleet"


def _stamp_player(
    sample_turn,
    player_id: int,
    *,
    status: int,
    statusturn: int,
    turn_number: int,
    username: str | None = None,
):
    def stamp(player):
        if player.id != player_id:
            return player
        updates: dict[str, object] = {"status": status, "statusturn": statusturn}
        if username is not None:
            updates["username"] = username
        return replace(player, **updates)

    return replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
        player=stamp(sample_turn.player),
        players=[stamp(player) for player in sample_turn.players],
    )


def _scope(turn, player_id: int) -> ExportScope:
    return ExportScope(
        game_id=GAME_ID,
        perspective=perspective(turn),
        turn=turn.settings.turn,
        player_id=player_id,
    )


def _ship_ledger(player_id: int) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            player_name="filled",
            records=[FleetShipRecord(record_id="should-drop")],
        ),
    )


@pytest.mark.parametrize(
    ("turn_number", "statusturn"),
    [(24, 24), (27, 24)],
)
def test_eliminated_player_empty_final_ledger_without_prior_or_scores(
    sample_turn,
    persistence,
    turn_number: int,
    statusturn: int,
):
    player_id = first_player_id(sample_turn)
    turn = _stamp_player(
        sample_turn,
        player_id,
        status=3,
        statusturn=statusturn,
        turn_number=turn_number,
        username="dead",
    )
    ctx = export_chain_query_context(
        turn,
        persistence=persistence,
        stored_turns={turn_number: turn},
    )
    scope = _scope(turn, player_id)
    walk = walk_dependency_tree(ctx, _FLEET, scope, visiting=set())
    assert walk.turn_unavailable is None
    pending_turns = [
        (analytic_id, pending.turn) for analytic_id, pending, _catalog in walk.pending_ensure
    ]
    assert pending_turns == [(_FLEET, turn_number)]

    planned = plan_compute_dag(
        ctx,
        _FLEET,
        scope,
        compute_registry=COMPUTE_REGISTRY,
    )
    assert len(planned) == 1
    assert planned[0].dependency_scopes == ()

    fleet_services = ctx.export_services[_FLEET]
    with (
        patch.object(
            fleet_services.persistence,
            "get_ledger",
            side_effect=AssertionError("eliminated fleet must not load a prior ledger"),
        ),
        patch(
            "api.analytics.fleet.chain.ensure_fleet_baseline_for_player",
            side_effect=AssertionError("eliminated fleet must not load a baseline"),
        ),
    ):
        job_wire = build_fleet_materialization_leg_job_wire(
            ComputeScope(
                analytic_id=_FLEET,
                game_id=GAME_ID,
                perspective=perspective(turn),
                turn=turn_number,
                player_id=player_id,
            ),
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
    assert job_wire["priorLedgerWire"] is None
    assert job_wire["baselineLedgerWire"] is None
    assert job_wire["eliminatedAtTurn"] is True
    assert job_wire["provenanceWire"]["turnEvidenceAtN"] is False
    assert job_wire["provenanceWire"]["priorLedgerAtNMinus1"] is False
    assert job_wire["provenanceWire"]["eliminatedAtTurn"] is True

    observed = run_fleet_observation_leg(job_wire)
    assert observed.payload["persistedLedgerWire"]["ledger"]["records"] == []

    compute_scope = ComputeScope(
        analytic_id=_FLEET,
        game_id=GAME_ID,
        perspective=perspective(turn),
        turn=turn_number,
        player_id=player_id,
    )
    ledger_persisted_events: list[tuple[int, int]] = []
    fleet_services.persistence.on_ledger_persisted = lambda event: ledger_persisted_events.append(
        (event.fleet_turn, event.player_id)
    )
    mark_before_observation = fleet_services.persistence.evidence_mark(
        GAME_ID,
        perspective(turn),
        player_id,
    )

    observation_wire = {
        "persistedLedgerWire": observed.payload["persistedLedgerWire"],
        "materializeTurn": turn_number,
        "fleetPersistLeg": "observation",
    }
    observation_deferred = FleetPersistencePolicy().persist(ctx, compute_scope, observation_wire)
    assert observation_deferred is None
    assert ledger_persisted_events == []
    assert fleet_services.persistence.has_final_ledger(
        GAME_ID,
        perspective(turn),
        turn_number,
        player_id,
    ) is False
    after_observation = fleet_services.persistence.get_ledger(
        GAME_ID,
        perspective(turn),
        turn_number,
        player_id,
    )
    assert after_observation is not None
    assert after_observation.ledger.records == []
    assert after_observation.provenance.turn_evidence_at_n is False
    assert after_observation.provenance.prior_ledger_at_n_minus_1 is False
    assert after_observation.provenance.eliminated_at_turn is False
    assert after_observation.provenance.is_final is False
    assert fleet_services.persistence.evidence_mark(
        GAME_ID,
        perspective(turn),
        player_id,
    ) == mark_before_observation

    finalization_wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(_ship_ledger(player_id)),
        "materializeTurn": turn_number,
        "fleetPersistLeg": "finalization",
    }
    finalization_deferred = FleetPersistencePolicy().persist(
        ctx, compute_scope, finalization_wire
    )
    assert finalization_deferred is not None
    assert ledger_persisted_events == []
    finalization_deferred()
    assert ledger_persisted_events == [(turn_number, player_id)]
    assert fleet_services.persistence.has_final_ledger(
        GAME_ID,
        perspective(turn),
        turn_number,
        player_id,
    )
    stored = fleet_services.persistence.get_ledger(
        GAME_ID,
        perspective(turn),
        turn_number,
        player_id,
    )
    assert stored is not None
    assert stored.ledger.records == []
    assert stored.provenance.turn_evidence_at_n is False
    assert stored.provenance.prior_ledger_at_n_minus_1 is False
    assert stored.provenance.eliminated_at_turn is True
    assert stored.provenance.is_final is True
    hydrated = FleetPersistencePolicy().satisfied_result_wire(ctx, compute_scope)
    assert hydrated == {"persistedLedgerWire": persisted_fleet_ledger_to_json(stored)}
    complete = wire_materialized_complete_event(
        persisted_fleet_ledger_from_json(hydrated["persistedLedgerWire"])
    )
    assert complete == {
        "type": "complete",
        "isFinal": True,
        "summary": "Fleet ledger materialization complete.",
    }


def test_turn_before_elimination_keeps_prior_fleet_and_scores_gate(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn = _stamp_player(
        sample_turn,
        player_id,
        status=3,
        statusturn=24,
        turn_number=23,
        username="dead",
    )
    ctx = export_chain_query_context(
        turn,
        persistence=persistence,
        stored_turns={23: turn},
    )
    walk = walk_dependency_tree(ctx, _FLEET, _scope(turn, player_id), visiting=set())
    assert walk.turn_unavailable == "turn_not_stored"
    assert walk.unavailable_turn == 22

    result_wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(_ship_ledger(player_id)),
        "materializeTurn": 23,
        "fleetPersistLeg": "finalization",
    }
    with pytest.raises(FleetScoresEvidenceOpenError) as raised:
        FleetPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=_FLEET,
                game_id=GAME_ID,
                perspective=perspective(turn),
                turn=23,
                player_id=player_id,
            ),
            result_wire,
        )
    assert raised.value.recovery is not None
    assert raised.value.recovery.step_kind == "tier_solve"
    assert raised.value.recovery.force_fresh is True


def test_slot_takeover_does_not_short_circuit(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    turn = _stamp_player(
        sample_turn,
        player_id,
        status=1,
        statusturn=90,
        turn_number=90,
        username="dead",
    )
    ctx = export_chain_query_context(
        turn,
        persistence=persistence,
        stored_turns={90: turn},
    )
    walk = walk_dependency_tree(ctx, _FLEET, _scope(turn, player_id), visiting=set())
    assert walk.turn_unavailable == "turn_not_stored"
    assert walk.unavailable_turn == 89

    result_wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(_ship_ledger(player_id)),
        "materializeTurn": 90,
        "fleetPersistLeg": "finalization",
    }
    with pytest.raises(FleetScoresEvidenceOpenError) as raised:
        FleetPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=_FLEET,
                game_id=GAME_ID,
                perspective=perspective(turn),
                turn=90,
                player_id=player_id,
            ),
            result_wire,
        )
    assert raised.value.recovery is not None
    assert raised.value.recovery.step_kind == "tier_solve"
