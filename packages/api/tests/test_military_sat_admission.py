"""SAT admission from pin-fail, unknown-class outgoing leave, and unknown-class idle-dock."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.types import FleetAcquisitionLedger
from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    REPORTED_HOST_TURN_SEGMENT_ID,
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import _run_corpus_prebuilt_inference
from api.analytics.military_score_inference.count_lattice import (
    CountLatticeClassEvent,
    CountLatticeSignal,
    DeparturePin,
    count_lattice_signal,
    departure_pin,
)
from api.analytics.military_score_inference.inference_api_payload import (
    format_inference_summary,
    inference_api_payload,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    new_ladder_state,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.military_sat_admission import (
    class_can_move_military,
    military_sat_admission,
    military_sat_refusal_from_turn,
    resolve_military_sat_admission,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceResult
from api.analytics.military_score_inference.policy_ladder import (
    finalize_policy_ladder_result,
    solve_with_policy_ladder,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    PublicScoreboardRow,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    UnknownLossBoundLeftover,
)

from tests.fixtures.military_score_inference import _observation, without_player_minefields
from tests.fixtures.pp_gap_transfer import (
    birds_row,
    federation_row,
    mixed_residual_receiver_row,
)
from tests.fixtures.ship_transfer_families import (
    _class_only_freighter_record,
    _known_warship_record,
    _multi_hull_unknown_warship,
    _peer_row,
    _singleton_unknown_hull_warship,
)

PLAYER_ID = 8
_EMPTY_PAIRING = PublicScoreboardPairing(
    matches=(),
    unmatched_warship_drop=0,
    unmatched_freighter_drop=0,
)


def _ledger(*records):
    return FleetAcquisitionLedger(player_id=PLAYER_ID, records=list(records))


def _pairing_and_idle_dock(observation, *, peer_rows=(), settings=None):
    row = public_scoreboard_row_from_observation(observation)
    pairing = classify_public_scoreboard_pairing(
        row,
        peer_rows,
        settings=settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    idle_dock = transfer_budget_for_row(
        row,
        settings=settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    return pairing, idle_dock


def _signal(observation, *, peer_rows=(), settings=None):
    pairing, idle_dock = _pairing_and_idle_dock(observation, peer_rows=peer_rows, settings=settings)
    return count_lattice_signal(observation, pairing, idle_dock)


def _pin(observation, records, this_turn_ships=(), *, hulls_by_id):
    return departure_pin(
        observation,
        _ledger(*records),
        this_turn_ships,
        hulls_by_id=hulls_by_id,
    )


def _admission(signal, pins, pairing=_EMPTY_PAIRING):
    return military_sat_admission(signal, pins, pairing)


def _resolve(observation, records, hulls_by_id, *, peer_rows=(), settings=None):
    pairing, idle_dock = _pairing_and_idle_dock(observation, peer_rows=peer_rows, settings=settings)
    return resolve_military_sat_admission(
        observation,
        pairing=pairing,
        idle_dock=idle_dock,
        prior_ledger=FleetAcquisitionLedger(
            player_id=observation.player_id,
            records=list(records),
        ),
        this_turn_ships=(),
        hulls_by_id=hulls_by_id,
    )


def _observation_from_row(row: PublicScoreboardRow) -> InferenceObservation:
    return InferenceObservation(
        player_id=row.player_id,
        turn=15,
        military_delta_2x=row.military_delta_2x,
        warship_delta=row.warship_delta,
        freighter_delta=row.freighter_delta,
        priority_point_delta=row.priority_point_delta,
        starbases_owned=row.starbases,
        is_after_ship_limit=False,
        planet_delta=row.planet_delta,
        starbase_delta=row.starbase_delta,
    )


def _warship_drop_signal() -> CountLatticeSignal:
    return CountLatticeSignal(
        events=(CountLatticeClassEvent(ship_class="warship", source="unmatched_drop", count=1),)
    )


def _freighter_drop_signal() -> CountLatticeSignal:
    return CountLatticeSignal(
        events=(CountLatticeClassEvent(ship_class="freighter", source="unmatched_drop", count=1),)
    )


def test_true_freighter_cannot_move_military():
    assert class_can_move_military("freighter") is False
    assert class_can_move_military("warship") is True
    assert class_can_move_military(None) is True


def test_quiet_turn_with_no_signal_admits_sat():
    admission = _admission(CountLatticeSignal(events=()), pins=())
    assert admission.admitted is True


def test_unpinned_warship_drop_refuses_sat():
    admission = _admission(
        _warship_drop_signal(),
        (DeparturePin(kind="fail", ship_class="warship"),),
    )
    assert admission.admitted is False
    assert admission.refused_class == "warship"


def test_pin_absence_on_warship_lattice_event_is_not_fail():
    admission = _admission(_warship_drop_signal(), pins=())
    assert admission.admitted is True
    assert admission.refused_class is None


def test_unknown_class_idle_dock_signal_refuses_sat():
    admission = _admission(
        CountLatticeSignal(
            events=(CountLatticeClassEvent(ship_class=None, source="idle_dock", count=1),)
        ),
        pins=(),
    )
    assert admission.admitted is False
    assert admission.refused_class is None


def test_pinned_idle_dock_class_without_pin_fail_admits_sat():
    admission = _admission(
        CountLatticeSignal(
            events=(CountLatticeClassEvent(ship_class="warship", source="idle_dock", count=1),)
        ),
        pins=(),
    )
    assert admission.admitted is True


def test_unpinned_freighter_only_drop_admits_sat():
    admission = _admission(
        _freighter_drop_signal(),
        (DeparturePin(kind="fail", ship_class="freighter"),),
    )
    assert admission.admitted is True


def test_exact_set_warship_pin_admits_sat():
    admission = _admission(
        _warship_drop_signal(),
        (DeparturePin(kind="exact_set", ship_class="warship", record_ids=("r1",)),),
    )
    assert admission.admitted is True


def test_spec_only_warship_pin_admits_sat():
    admission = _admission(
        _warship_drop_signal(),
        (DeparturePin(kind="spec_only", ship_class="warship"),),
    )
    assert admission.admitted is True


def test_unique_fill_warship_drop_does_not_pin_and_refuses_sat(synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    signal = _signal(observation)
    pins = _pin(
        observation,
        (_singleton_unknown_hull_warship(),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert signal
    assert pins == (DeparturePin(kind="fail", ship_class="warship"),)
    assert _admission(signal, pins).admitted is False


def test_fan_without_envelopes_does_not_pin_and_refuses_sat(synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    signal = _signal(observation)
    pins = _pin(
        observation,
        (_multi_hull_unknown_warship(),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship"),)
    assert _admission(signal, pins).admitted is False


def test_rst_known_exact_set_admits_sat(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    signal = _signal(observation)
    pins = _pin(
        observation,
        (record,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins[0].kind == "exact_set"
    assert _admission(signal, pins).admitted is True


def test_spec_only_identical_known_hulls_admit_sat(synthetic_catalog_context):
    records = tuple(
        _known_warship_record(synthetic_catalog_context, record_id=f"flame-{index}")[0]
        for index in range(10)
    )
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    signal = _signal(observation)
    pins = _pin(
        observation,
        records,
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="spec_only", ship_class="warship", record_ids=()),)
    assert _admission(signal, pins).admitted is True


def test_unpinned_freighter_drop_with_class_only_record_admits_sat(
    synthetic_catalog_context,
):
    observation = _observation(warship_delta=0, freighter_delta=-1, military_delta_2x=0)
    signal = _signal(observation)
    pins = _pin(
        observation,
        (_class_only_freighter_record(),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert any(event.ship_class == "freighter" for event in signal.events)
    assert pins == (DeparturePin(kind="fail", ship_class="freighter"),)
    assert _admission(signal, pins).admitted is True


def test_resolve_admission_uses_pin_not_unique_fill(synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    admission = _resolve(
        observation,
        (_singleton_unknown_hull_warship(),),
        synthetic_catalog_context["hulls_by_id"],
    )
    assert admission.admitted is False
    assert admission.refused_class == "warship"


def test_military_sat_refused_payload_is_uncharacterized_roster_not_no_exact_solution():
    result = InferenceResult(
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solutions=(),
        diagnostics={"reason": "unpinned_military_departure", "satAdmitted": False},
        leftover=UnknownLossBoundLeftover(lower_bound_2x=0),
        lattice_signatures=(),
    )
    payload = inference_api_payload(
        status=result.status,
        summary=format_inference_summary(result),
        solutions=result.solutions,
        diagnostics=result.diagnostics,
        placeholders=[],
        leftover=result.leftover,
        lattice_signatures=result.lattice_signatures,
    )
    assert payload["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert payload["status"] != STATUS_NO_EXACT_SOLUTION
    assert payload["isComplete"] is True
    assert payload["solutions"] == []
    assert payload["placeholders"] == []
    assert payload["leftover"]["kind"] == "unknown_loss_bound"
    assert "unexplainedMilitaryDelta2x" not in payload
    assert "Uncharacterized roster" in payload["summary"]
    assert "No feasible build explanation found" not in payload["summary"]


def _patch_sat(monkeypatch, calls: list):
    def _solve(problem, **kwargs):
        calls.append(problem)
        return InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={})

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.leftover_0_solutions",
        lambda solutions, *_args, **_kwargs: list(solutions),
    )


def _patch_catalog_must_not_build(monkeypatch, calls: list):
    def _catalog(*args, **kwargs):
        calls.append(1)
        raise AssertionError("military catalog must not be built")

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        _catalog,
    )


def _unpinned_warship_drop_observation_turn(sample_turn):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    turn = without_player_minefields(sample_turn, observation.player_id)
    return observation, turn


def _quiet_tier_job_callbacks():
    return InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=lambda _observation: None,
    )


def test_unpinned_warship_drop_does_not_build_catalog_or_run_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    _patch_catalog_must_not_build(monkeypatch, catalog_calls)
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    result, catalog, problem, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is None
    assert problem is None
    assert attempted == []
    assert sat_calls == []
    assert catalog_calls == []


def test_rst_known_exact_set_still_enters_sat(sample_turn, monkeypatch, synthetic_catalog_context):
    sat_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    record, _ = _known_warship_record(synthetic_catalog_context)
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    result, catalog, _problem, attempted, _ = solve_with_policy_ladder(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        prior_fleet_records=(record,),
    )
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is not None
    assert attempted
    assert sat_calls


def test_unpinned_freighter_only_drop_still_enters_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    observation = _observation(warship_delta=0, freighter_delta=-1, military_delta_2x=0)
    result, catalog, _problem, attempted, _ = solve_with_policy_ladder(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        prior_fleet_records=(_class_only_freighter_record(),),
    )
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is not None
    assert attempted
    assert sat_calls


def test_spec_only_pin_still_enters_sat(sample_turn, monkeypatch, synthetic_catalog_context):
    sat_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    records = tuple(
        _known_warship_record(synthetic_catalog_context, record_id=f"same-{index}")[0]
        for index in range(10)
    )
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    result, catalog, _problem, attempted, _ = solve_with_policy_ladder(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        prior_fleet_records=records,
    )
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is not None
    assert attempted
    assert sat_calls


def _peer_score(
    sample_turn, *, ownerid: int, shipchange: int, freighterchange: int, militarychange: int
):
    return replace(
        sample_turn.scores[0],
        ownerid=ownerid,
        shipchange=shipchange,
        freighterchange=freighterchange,
        militarychange=militarychange,
        planetchange=0,
        starbasechange=0,
    )


def _turn_with_peer(sample_turn, observation, peer_score):
    return replace(
        without_player_minefields(sample_turn, observation.player_id),
        scores=(peer_score,),
    )


def test_known_class_acquired_warship_with_no_drop_admits_sat(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    observation = _observation(
        warship_delta=1,
        freighter_delta=0,
        military_delta_2x=military_2x,
    )
    peer = _peer_row(3, warship=-1, military_2x=-military_2x)
    pairing, _idle_dock = _pairing_and_idle_dock(observation, peer_rows=(peer,))
    assert pairing.matches[0].family == "acquired"
    assert pairing.matches[0].warship_delta == 1
    admission = _resolve(
        observation,
        (record,),
        synthetic_catalog_context["hulls_by_id"],
        peer_rows=(peer,),
    )
    assert not any(pin.ship_class == "warship" for pin in admission.pins)
    assert any(
        event.source == "pairing" and event.ship_class == "warship"
        for event in admission.signal.events
    )
    assert admission.admitted is True


def test_class_flip_receiving_warship_admits_sat(synthetic_catalog_context):
    observation = _observation(warship_delta=1, freighter_delta=-1, military_delta_2x=40)
    peer = _peer_row(3, warship=-1, freighter=1, military_2x=-40)
    pairing, _idle_dock = _pairing_and_idle_dock(observation, peer_rows=(peer,))
    assert pairing.matches[0].family == "trade"
    assert pairing.matches[0].warship_delta == 1
    admission = _resolve(
        observation,
        (_class_only_freighter_record(),),
        synthetic_catalog_context["hulls_by_id"],
        peer_rows=(peer,),
    )
    assert any(
        event.source == "pairing" and event.ship_class == "warship"
        for event in admission.signal.events
    )
    assert not any(pin.ship_class == "warship" for pin in admission.pins)
    assert any(pin.kind == "fail" and pin.ship_class == "freighter" for pin in admission.pins)
    assert admission.admitted is True


def test_class_flip_receiving_warship_still_enters_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    observation = _observation(
        warship_delta=1,
        freighter_delta=-1,
        military_delta_2x=40,
        starbases_owned=0,
    )
    turn = _turn_with_peer(
        sample_turn,
        observation,
        _peer_score(
            sample_turn,
            ownerid=3,
            shipchange=-1,
            freighterchange=1,
            militarychange=-20,
        ),
    )
    result, catalog, _problem, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        prior_fleet_records=(_class_only_freighter_record(),),
    )
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is not None
    assert attempted
    assert sat_calls


def test_count_flat_military_trade_admits_sat(synthetic_catalog_context):
    observation = _observation(warship_delta=0, freighter_delta=0, military_delta_2x=-40)
    peer = _peer_row(3, warship=0, military_2x=40)
    pairing, _idle_dock = _pairing_and_idle_dock(observation, peer_rows=(peer,))
    assert pairing.matches[0].family == "trade"
    assert pairing.matches[0].warship_delta == 0
    admission = _resolve(
        observation,
        (),
        synthetic_catalog_context["hulls_by_id"],
        peer_rows=(peer,),
    )
    assert any(
        event.source == "pairing" and event.ship_class is None for event in admission.signal.events
    )
    assert admission.pins == ()
    assert admission.admitted is True


def test_outgoing_unpinned_warship_gift_refuses_sat(synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    peer = _peer_row(3, warship=1, military_2x=40)
    pairing, _idle_dock = _pairing_and_idle_dock(observation, peer_rows=(peer,))
    assert pairing.matches[0].family == "gift"
    assert pairing.matches[0].warship_delta == -1
    admission = _resolve(
        observation,
        (_singleton_unknown_hull_warship(),),
        synthetic_catalog_context["hulls_by_id"],
        peer_rows=(peer,),
    )
    assert admission.pins == (DeparturePin(kind="fail", ship_class="warship"),)
    assert admission.admitted is False
    assert admission.refused_class == "warship"


def test_birds_row_unknown_class_idle_dock_refuses_sat(sample_turn, synthetic_catalog_context):
    observation = _observation_from_row(birds_row())
    admission = _resolve(
        observation,
        (),
        synthetic_catalog_context["hulls_by_id"],
        settings=sample_turn.settings,
    )
    assert any(
        event.source == "idle_dock" and event.ship_class is None
        for event in admission.signal.events
    )
    assert admission.pins == ()
    assert admission.admitted is False
    assert admission.refused_class is None


def test_unknown_class_outgoing_gift_refuses_sat(sample_turn, synthetic_catalog_context):
    observation = _observation_from_row(federation_row())
    peer = mixed_residual_receiver_row()
    pairing, _idle_dock = _pairing_and_idle_dock(
        observation, peer_rows=(peer,), settings=sample_turn.settings
    )
    assert pairing.matches[0].family == "gift"
    assert pairing.matches[0].is_unpinned_class_choice()
    admission = _resolve(
        observation,
        (),
        synthetic_catalog_context["hulls_by_id"],
        peer_rows=(peer,),
        settings=sample_turn.settings,
    )
    assert admission.pins == ()
    assert admission.admitted is False
    assert admission.refused_class is None


def test_tier_step_refuses_before_catalog_or_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    _patch_catalog_must_not_build(monkeypatch, catalog_calls)
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(None)),
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=1.0,
    )
    assert state.ladder_complete is True
    assert state.catalog is None
    assert state.problem is None
    assert state.last_status == STATUS_UNCHARACTERIZED_ROSTER
    assert state.refused_result is not None
    assert state.refused_result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert state.refused_result.leftover is not None
    assert state.refused_result.solutions == ()
    assert state.policy_steps_attempted == []
    assert state.started_at is None
    assert sat_calls == []
    assert catalog_calls == []
    assert state.sat_admission is not None
    assert state.sat_admission.admitted is False
    assert state.scoreboard_pairing is not None


def test_finalize_returns_stashed_refuse_without_recompute(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    _patch_catalog_must_not_build(monkeypatch, catalog_calls)
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(None)),
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=1.0,
    )
    stashed = state.refused_result
    assert stashed is not None

    def _must_not_recompute(*_args, **_kwargs):
        raise AssertionError("refuse must not re-run admission or emit")

    monkeypatch.setattr(
        "api.analytics.military_score_inference.military_sat_admission.military_sat_refusal_from_turn",
        _must_not_recompute,
    )
    result, catalog, problem, *_ = finalize_policy_ladder_result(state, observation, turn)
    assert result is stashed
    assert catalog is None
    assert problem is None
    assert sat_calls == []
    assert catalog_calls == []


def test_finalize_does_not_emit_hollow_uncharacterized_roster(sample_turn):
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(None)),
        last_status=STATUS_UNCHARACTERIZED_ROSTER,
        last_diagnostics={"reason": "unpinned_military_departure", "satAdmitted": False},
    )
    result, *_ = finalize_policy_ladder_result(state, observation, turn)
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert result.leftover is None
    assert result.lattice_signatures == ()


def test_refusal_from_turn_classifies_pairing_once(sample_turn, monkeypatch):
    pairing_calls: list[int] = []
    idle_dock_calls: list[int] = []
    real_classify = classify_public_scoreboard_pairing
    real_idle_dock = transfer_budget_for_row

    def _classify(*args, **kwargs):
        pairing_calls.append(1)
        return real_classify(*args, **kwargs)

    def _idle_dock(*args, **kwargs):
        idle_dock_calls.append(1)
        return real_idle_dock(*args, **kwargs)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.military_sat_admission.classify_public_scoreboard_pairing",
        _classify,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.military_sat_admission.transfer_budget_for_row",
        _idle_dock,
    )
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    result = military_sat_refusal_from_turn(
        observation,
        turn,
        (_singleton_unknown_hull_warship(),),
    )
    assert result is not None
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert result.leftover is not None
    assert pairing_calls == [1]
    assert idle_dock_calls == [1]


def test_stream_tier_job_surfaces_military_sat_refused_without_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    _patch_catalog_must_not_build(monkeypatch, catalog_calls)
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    session = InferenceRowStreamSession(
        player_id=observation.player_id,
        observation=observation,
        turn=turn,
        game_id=628580,
        perspective=1,
        turn_number=turn.settings.turn,
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    run = RowRun(session)
    run.ladder_state = new_ladder_state(session)
    outcome = run_inference_tier_job(run, _quiet_tier_job_callbacks())
    assert outcome.enqueue_continuation is False
    assert outcome.row_complete is not None
    assert outcome.row_complete.result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert outcome.row_complete.result is run.ladder_state.refused_result
    assert outcome.row_complete.result.leftover is not None
    assert outcome.row_complete.wire_payload.is_complete is True
    assert sat_calls == []
    assert catalog_calls == []


def test_stream_sat_refuse_does_not_continue_accelerated_segments(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []
    _patch_sat(monkeypatch, sat_calls)
    _patch_catalog_must_not_build(monkeypatch, catalog_calls)
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    score = next(row for row in turn.scores if row.ownerid == observation.player_id)
    orchestration = InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_SPLIT,
        row_score=score,
        row_turn=turn,
        solve_score=score,
        solve_turn=turn,
        segments=(
            AcceleratedInferenceSegment(
                segment_id=ACCEL_WINDOW_SEGMENT_ID,
                host_turn=1,
                military_delta_2x=-40,
                warship_delta=-1,
                freighter_delta=0,
                priority_point_delta=0,
            ),
            AcceleratedInferenceSegment(
                segment_id=REPORTED_HOST_TURN_SEGMENT_ID,
                host_turn=2,
                military_delta_2x=20,
                warship_delta=1,
                freighter_delta=0,
                priority_point_delta=0,
            ),
        ),
    )
    session = InferenceRowStreamSession(
        player_id=observation.player_id,
        observation=observation,
        turn=turn,
        game_id=628580,
        perspective=1,
        turn_number=turn.settings.turn,
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    run = RowRun(session)
    run.orchestration = orchestration
    run.ladder_state = orchestration.new_ladder_state(session)
    outcome = run_inference_tier_job(run, _quiet_tier_job_callbacks())
    assert outcome.enqueue_continuation is False
    assert outcome.next_ladder_state is None
    assert outcome.row_complete is not None
    assert outcome.row_complete.result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert outcome.row_complete.result is run.ladder_state.refused_result
    assert outcome.row_complete.result.leftover is not None
    assert outcome.row_complete.wire_payload.is_complete is True
    assert orchestration.segment_solves == []
    assert sat_calls == []
    assert catalog_calls == []


def test_corpus_prebuilt_does_not_run_sat_when_refused(sample_turn, monkeypatch):
    sat_calls: list = []
    problem_calls: list = []

    def _solve(problem, **kwargs):
        sat_calls.append(problem)
        return InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={})

    def _problem(*args, **kwargs):
        problem_calls.append(1)
        raise AssertionError("corpus SAT must not build a problem when refused")

    monkeypatch.setattr(
        "api.analytics.military_score_inference.analytic.solve_inference_problem",
        _solve,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.analytic.build_inference_problem",
        _problem,
    )
    observation, turn = _unpinned_warship_drop_observation_turn(sample_turn)
    result, catalog, problem, attempted, _ = _run_corpus_prebuilt_inference(
        observation,
        ActionCatalog((), (), {}),
        turn=turn,
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert result.leftover is not None
    assert catalog is None
    assert problem is None
    assert attempted == []
    assert sat_calls == []
    assert problem_calls == []
