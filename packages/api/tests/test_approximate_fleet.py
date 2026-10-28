"""Approximate fleet file: prior copy, sightings, and terminal replacement."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.approximate_fleet import terminal_fleet_ledger
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    _FleetPlayerOrchestratorRun,
    get_fleet_table_stream_scheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetCountDiscrepancy,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetMaterializationProvenance,
    FleetPossiblyLost,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.options import TurnAnalyticsOptions
from api.compute.scope import WILDCARD, ComputeScope
from api.compute.wire import DependencyOutputs
from api.errors import FleetScoresEvidenceOpenError
from api.models.enums import PlayerStatus

from tests.fleet_fixtures import single_ship_turn

_FLEET = "fleet"


def _score_owner(turn) -> int:
    return next(score.ownerid for score in turn.scores if score.turn == turn.settings.turn)


def _turn(
    *,
    turn_number: int,
    ship_ids: tuple[int, ...],
    capitalships: int,
    freighters: int,
    shipchange: int = 0,
):
    base = single_ship_turn(
        turn_number=turn_number,
        ship_id=ship_ids[0] if ship_ids else 1,
        owner_id=1,
        x=1000,
        y=1000,
        hull_id=1,
    )
    owner_id = base.scores[0].ownerid
    ships = [
        replace(base.ships[0], id=ship_id, ownerid=owner_id, x=1000 + ship_id, y=1000)
        for ship_id in ship_ids
    ]
    scored_owner = False
    scores = []
    for score in base.scores:
        if score.ownerid == owner_id and not scored_owner:
            scores.append(
                replace(
                    score,
                    turn=turn_number,
                    capitalships=capitalships,
                    freighters=freighters,
                    shipchange=shipchange,
                    freighterchange=0,
                )
            )
            scored_owner = True
            continue
        scores.append(replace(score, turn=turn_number))
    return replace(
        base,
        settings=replace(base.settings, turn=turn_number, acceleratedturns=0),
        game=replace(base.game, turn=turn_number),
        ships=ships,
        scores=scores,
    )


def _record(
    record_id: str,
    *,
    ship_id: int | None,
    hull_id: int | None = None,
    negative_delta_turn: int | None = None,
) -> FleetShipRecord:
    events: list[FleetEvidenceEvent] = []
    if negative_delta_turn is not None:
        events.append(
            FleetEvidenceEvent(
                event_id=str(uuid.uuid4()),
                kind="scoreboard_delta",
                turn=negative_delta_turn,
                source="scoreboard",
                payload={"shipClass": "warship", "warshipDelta": -1, "freighterDelta": 0},
            )
        )
    return FleetShipRecord(
        record_id=record_id,
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(ship_id) if ship_id is not None else FleetFieldUnknown(),
            hull=FleetFieldKnown(hull_id) if hull_id is not None else FleetFieldUnknown(),
        ),
        events=events,
    )


def _prior(
    player_id: int,
    records: list[FleetShipRecord],
    *,
    final: bool = False,
    discrepancy: FleetCountDiscrepancy | None = None,
) -> PersistedFleetLedger:
    ledger = FleetAcquisitionLedger(player_id=player_id, player_name="prior", records=records)
    ledger.discrepancy = discrepancy
    provenance = (
        FleetMaterializationProvenance(turn_evidence_at_n=True, prior_ledger_at_n_minus_1=True)
        if final
        else FleetMaterializationProvenance()
    )
    return PersistedFleetLedger(ledger=ledger, provenance=provenance)


def _bind(turn, *stored: object):
    player_id = _score_owner(turn)
    turns = {item.settings.turn: item for item in (turn, *stored)}
    services = build_ephemeral_fleet_compute_services(
        turn,
        game_id=turn.game.id,
        perspective=turn.player.id,
        stored_turns=turns,
    )
    ctx = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=services.load_turn,
        export_services={_FLEET: services},
        game_id=services.game_id,
        perspective=services.perspective,
    )
    return services, ctx, player_id


def _scope(services, turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=_FLEET,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn.settings.turn,
        player_id=player_id,
    )


def _write_observation(services, ctx, turn, player_id: int):
    job_wire = build_fleet_materialization_leg_job_wire(
        _scope(services, turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    observed = run_fleet_observation_leg(job_wire)
    assert observed.payload is not None
    callback = FleetPersistencePolicy().persist(
        ctx, _scope(services, turn, player_id), observed.payload
    )
    stored = services.persistence.get_ledger(
        services.game_id,
        services.perspective,
        turn.settings.turn,
        player_id,
    )
    assert stored is not None
    return stored, callback


def test_approximate_write_folds_prior_and_sightings_without_a_solve() -> None:
    turn = _turn(
        turn_number=5,
        ship_ids=(20, 30),
        capitalships=1,
        freighters=0,
        shipchange=4,
    )
    player_id = _score_owner(turn)
    unsighted = _record("stay", ship_id=10)
    unsighted.qualifiers.possibly_lost = FleetPossiblyLost(since_turn=4, source="scoreboard")
    sighted = _record("seen", ship_id=20, negative_delta_turn=4)
    prior = _prior(
        player_id,
        [unsighted, sighted],
        discrepancy=FleetCountDiscrepancy(
            host_turn=4,
            active_row_count=9,
            scoreboard_implied_count=1,
        ),
    )
    services, ctx, player_id = _bind(turn)
    services.persistence.put_ledger(
        services.game_id,
        services.perspective,
        4,
        player_id,
        prior,
    )
    stored, callback = _write_observation(services, ctx, turn, player_id)
    if callback is not None:
        callback()

    by_id = {record.record_id: record for record in stored.ledger.records}
    assert set(by_id) >= {"stay", "seen"}
    assert by_id["stay"].qualifiers.possibly_lost is not None
    assert by_id["stay"].qualifiers.alibi is None
    assert by_id["stay"].last_seen is None or by_id["stay"].last_seen.turn != 5
    assert by_id["seen"].qualifiers.alibi is not None
    assert by_id["seen"].qualifiers.alibi.sighting_turn == 5
    assert any(record.record_id not in {"stay", "seen"} for record in stored.ledger.records)
    assert not any(
        event.kind == "count_collapse"
        for record in stored.ledger.records
        for event in record.events
    )
    assert not any(
        event.kind == "scoreboard_delta" and event.turn == 5
        for record in stored.ledger.records
        for event in record.events
    )
    assert stored.ledger.discrepancy is not None
    assert stored.ledger.discrepancy.host_turn == 5
    assert (
        stored.ledger.discrepancy.active_row_count
        > stored.ledger.discrepancy.scoreboard_implied_count
    )
    assert stored.ledger.discrepancy.active_row_count != 9
    assert stored.provenance.turn_evidence_at_n is False
    assert stored.provenance.prior_ledger_at_n_minus_1 is False
    assert (
        services.persistence.has_final_ledger(
            services.game_id,
            services.perspective,
            5,
            player_id,
        )
        is False
    )
    side_channel: list[object] = []
    services.persistence.on_ledger_persisted = side_channel.append
    if callback is not None:
        callback()
    assert side_channel == []


def test_missing_prior_is_not_created() -> None:
    turn = _turn(turn_number=5, ship_ids=(7,), capitalships=5, freighters=0)
    services, ctx, player_id = _bind(turn)
    stored, _callback = _write_observation(services, ctx, turn, player_id)
    assert (
        services.persistence.get_ledger(services.game_id, services.perspective, 4, player_id)
        is None
    )
    assert stored.ledger.records
    assert stored.ledger.discrepancy is None
    assert stored.provenance.turn_evidence_at_n is False
    assert stored.provenance.prior_ledger_at_n_minus_1 is False


def test_baseline_turn_marks_prior_leg_without_a_file() -> None:
    turn = _turn(turn_number=1, ship_ids=(7,), capitalships=1, freighters=0)
    services, ctx, player_id = _bind(turn)
    stored, _callback = _write_observation(services, ctx, turn, player_id)
    assert stored.provenance.turn_evidence_at_n is False
    assert stored.provenance.prior_ledger_at_n_minus_1 is True
    assert (
        services.persistence.has_final_ledger(
            services.game_id,
            services.perspective,
            1,
            player_id,
        )
        is False
    )


def test_ensure_final_prior_sets_prior_leg() -> None:
    turn = _turn(turn_number=5, ship_ids=(7,), capitalships=1, freighters=0)
    services, ctx, player_id = _bind(turn)
    services.persistence.put_ledger(
        services.game_id,
        services.perspective,
        4,
        player_id,
        _prior(player_id, [_record("old", ship_id=1)], final=True),
    )
    stored, _callback = _write_observation(services, ctx, turn, player_id)
    assert stored.provenance.prior_ledger_at_n_minus_1 is True
    assert stored.provenance.turn_evidence_at_n is False
    assert (
        services.persistence.ledger_is_ensure_final(
            services.game_id,
            services.perspective,
            5,
            player_id,
            stored,
        )
        is False
    )


def test_non_terminal_scoreboard_leaves_the_approximate_file() -> None:
    turn = _turn(
        turn_number=5,
        ship_ids=(7,),
        capitalships=0,
        freighters=0,
        shipchange=2,
    )
    services, ctx, player_id = _bind(turn)
    stored, _callback = _write_observation(services, ctx, turn, player_id)
    before = persisted_fleet_ledger_to_json(stored)
    wire = {
        "persistedLedgerWire": before,
        "materializeTurn": 5,
        "fleetPersistLeg": "finalization",
    }
    try:
        FleetPersistencePolicy().persist(ctx, _scope(services, turn, player_id), wire)
    except FleetScoresEvidenceOpenError:
        pass
    else:
        raise AssertionError("open scoreboard must leave the approximate file in place")
    after = services.persistence.get_ledger(services.game_id, services.perspective, 5, player_id)
    assert after is not None
    assert persisted_fleet_ledger_to_json(after) == before


def test_terminal_scoreboard_replaces_the_file_and_wakes_the_side_channel() -> None:
    turn = _turn(
        turn_number=1,
        ship_ids=(7,),
        capitalships=2,
        freighters=0,
        shipchange=1,
    )
    services, ctx, player_id = _bind(turn)
    approximate, observation_callback = _write_observation(services, ctx, turn, player_id)
    assert not any(
        event.kind == "scoreboard_delta"
        for record in approximate.ledger.records
        for event in record.events
    )
    side_channel: list[object] = []
    services.persistence.on_ledger_persisted = side_channel.append
    if observation_callback is not None:
        observation_callback()
    assert side_channel == []

    wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(approximate),
        "materializeTurn": 1,
        "fleetPersistLeg": "finalization",
    }
    callback = FleetPersistencePolicy().persist(ctx, _scope(services, turn, player_id), wire)
    assert callback is not None
    callback()
    replaced = services.persistence.get_ledger(services.game_id, services.perspective, 1, player_id)
    assert replaced is not None
    assert any(
        event.kind == "scoreboard_delta"
        for record in replaced.ledger.records
        for event in record.events
    )
    assert replaced.provenance.turn_evidence_at_n is True
    assert replaced.provenance.prior_ledger_at_n_minus_1 is True
    assert replaced.ledger.discrepancy is None
    assert side_channel


def test_terminal_replacement_collapses_and_clears_surplus() -> None:
    turn = _turn(turn_number=6, ship_ids=(7,), capitalships=1, freighters=0)
    turn = replace(turn, ships=[])
    player_id = _score_owner(turn)
    survivor = _record("known", ship_id=4, hull_id=1)
    absorbable = _record("extra", ship_id=None)
    absorbable.events.append(
        FleetEvidenceEvent(
            event_id=str(uuid.uuid4()),
            kind="scoreboard_delta",
            turn=5,
            source="scoreboard",
            payload={"shipClass": "warship", "warshipDelta": 1, "freighterDelta": 0},
        )
    )
    ledger = terminal_fleet_ledger(
        FleetAcquisitionLedger(player_id=player_id, records=[survivor, absorbable]),
        turn,
        game_id=turn.game.id,
        perspective=turn.player.id,
        inference_materialization=None,
    )
    by_id = {record.record_id: record for record in ledger.records}
    assert by_id["extra"].disposition == "merged"
    assert any(event.kind == "count_collapse" for event in by_id["extra"].events)
    assert ledger.discrepancy is None


def test_later_prior_save_replaces_the_approximate_file() -> None:
    turn5 = _turn(turn_number=5, ship_ids=(7,), capitalships=3, freighters=0)
    turn4 = _turn(turn_number=4, ship_ids=(8,), capitalships=3, freighters=0)
    turn3 = _turn(turn_number=3, ship_ids=(9,), capitalships=3, freighters=0)
    player_id = _score_owner(turn5)
    services, ctx5, player_id = _bind(turn5, turn4, turn3)
    services.persistence.put_ledger(
        services.game_id,
        services.perspective,
        4,
        player_id,
        _prior(player_id, [_record("old-ship", ship_id=11)]),
    )
    first, _callback = _write_observation(services, ctx5, turn5, player_id)
    assert any(record.record_id == "old-ship" for record in first.ledger.records)

    ctx4 = make_analytic_query_context(
        turn4,
        TurnAnalyticsOptions(),
        load_turn=services.load_turn,
        export_services={_FLEET: services},
        game_id=services.game_id,
        perspective=services.perspective,
    )
    services.persistence.put_ledger(
        services.game_id,
        services.perspective,
        3,
        player_id,
        _prior(player_id, [_record("new-ship", ship_id=12)]),
    )
    _replaced_prior, prior_callback = _write_observation(services, ctx4, turn4, player_id)
    assert prior_callback is not None
    prior_callback()
    refreshed = services.persistence.get_ledger(
        services.game_id, services.perspective, 5, player_id
    )
    assert refreshed is not None
    ids = {record.record_id for record in refreshed.ledger.records}
    assert "new-ship" in ids
    assert "old-ship" not in ids
    assert refreshed.provenance.turn_evidence_at_n is False


def test_eliminated_player_is_not_an_approximate_fleet(sample_turn) -> None:
    player_id = sample_turn.scores[0].ownerid
    turn_number = 6
    turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
        scores=[replace(score, turn=turn_number) for score in sample_turn.scores],
        player=replace(sample_turn.player, status=PlayerStatus.ELIMINATED, statusturn=turn_number)
        if sample_turn.player.id == player_id
        else sample_turn.player,
        players=[
            replace(player, status=PlayerStatus.ELIMINATED, statusturn=turn_number)
            if player.id == player_id
            else player
            for player in sample_turn.players
        ],
    )
    services, ctx, player_id = _bind(turn)
    job_wire = build_fleet_materialization_leg_job_wire(
        _scope(services, turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert job_wire["eliminatedAtTurn"] is True
    observed = run_fleet_observation_leg(job_wire)
    assert observed.payload is not None
    callback = FleetPersistencePolicy().persist(
        ctx,
        _scope(services, turn, player_id),
        observed.payload,
    )
    assert callback is None
    stored = services.persistence.get_ledger(
        services.game_id,
        services.perspective,
        turn_number,
        player_id,
    )
    assert stored is not None
    assert stored.ledger.records == []
    assert stored.provenance.turn_evidence_at_n is False
    assert stored.provenance.is_final is False


def test_saved_approximate_file_replaces_turn_load_rows() -> None:
    reset_fleet_table_stream_scheduler_for_tests()
    turn = _turn(turn_number=5, ship_ids=(7,), capitalships=1, freighters=0)
    services, ctx, player_id = _bind(turn)
    scheduler = get_fleet_table_stream_scheduler()
    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=turn,
        game_id=services.game_id,
        perspective=services.perspective,
    )
    scheduler._runs[session.run_id] = _FleetPlayerOrchestratorRun(
        session=session,
        host_turn_number=5,
        progress_tracker=FleetLedgerWireProgressTracker(host_turn=turn),
        root_scope=_scope(services, turn, player_id),
    )
    _write_observation(services, ctx, turn, player_id)
    events: list[dict[str, object]] = []
    while not session.event_queue.empty():
        events.append(session.event_queue.get_nowait())
    ledger_events = [event for event in events if event.get("type") == "ledger_updated"]
    assert ledger_events
    assert ledger_events[-1].get("replacesTurnLoad") is not False
    reset_fleet_table_stream_scheduler_for_tests()


def test_later_file_refresh_and_final_commit_fail_closed() -> None:
    turn = _turn(turn_number=5, ship_ids=(7,), capitalships=1, freighters=0)
    services, _ctx, player_id = _bind(turn)
    policy = FleetPersistencePolicy()
    concrete = _scope(services, turn, player_id)
    wildcard_turn = ComputeScope(
        analytic_id=_FLEET,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=WILDCARD,
        player_id=player_id,
    )
    persisted = _prior(player_id, [])

    with pytest.raises(TypeError, match="FleetComputeServices"):
        policy._refresh_following_callback(object(), concrete)
    with pytest.raises(TypeError, match="FleetComputeServices"):
        policy._commit_living_final(object(), concrete, {}, persisted)
    with pytest.raises(ValueError, match="concrete turn"):
        policy._refresh_following_callback(services, wildcard_turn)
    with pytest.raises(ValueError, match="concrete turn"):
        policy._commit_living_final(services, wildcard_turn, {}, persisted)
