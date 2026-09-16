"""SAT admission from count-lattice signal and departure pin (#487)."""

from __future__ import annotations

from api.analytics.fleet.types import FleetAcquisitionLedger
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
from api.analytics.military_score_inference.military_sat_admission import (
    STATUS_MILITARY_SAT_REFUSED,
    class_can_move_military,
    military_sat_admission,
    military_sat_refusal_result,
    resolve_military_sat_admission,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_NO_EXACT_SOLUTION

from tests.fixtures.military_score_inference import _observation, without_player_minefields
from tests.fixtures.ship_transfer_families import (
    _class_only_freighter_record,
    _known_warship_record,
    _multi_hull_unknown_warship,
    _singleton_unknown_hull_warship,
)

PLAYER_ID = 8


def _ledger(*records):
    return FleetAcquisitionLedger(player_id=PLAYER_ID, records=list(records))


def _signal(observation, *, peer_rows=(), settings=None):
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
    return count_lattice_signal(observation, pairing, idle_dock)


def _pin(observation, records, this_turn_ships=(), *, hulls_by_id):
    return departure_pin(
        observation,
        _ledger(*records),
        this_turn_ships,
        hulls_by_id=hulls_by_id,
    )


def _admission(signal, pins):
    return military_sat_admission(signal, pins)


def _warship_drop_signal() -> CountLatticeSignal:
    return CountLatticeSignal(
        events=(CountLatticeClassEvent(ship_class="warship", source="unmatched_drop", count=1),)
    )


def _freighter_drop_signal() -> CountLatticeSignal:
    return CountLatticeSignal(
        events=(CountLatticeClassEvent(ship_class="freighter", source="unmatched_drop", count=1),)
    )


def _unknown_class_signal() -> CountLatticeSignal:
    return CountLatticeSignal(
        events=(CountLatticeClassEvent(ship_class=None, source="pairing", count=1),)
    )


def test_true_freighter_cannot_move_military():
    assert class_can_move_military("freighter") is False
    assert class_can_move_military("warship") is True
    assert class_can_move_military(None) is True


def test_quiet_turn_with_no_signal_admits_sat():
    admission = _admission(CountLatticeSignal(events=()), pins=())
    assert admission.admitted is True
    assert military_sat_refusal_result(admission) is None


def test_unpinned_warship_drop_refuses_sat():
    admission = _admission(
        _warship_drop_signal(),
        (DeparturePin(kind="fail", ship_class="warship"),),
    )
    assert admission.admitted is False
    assert admission.refused_class == "warship"
    refused = military_sat_refusal_result(admission)
    assert refused is not None
    assert refused.status == STATUS_MILITARY_SAT_REFUSED
    assert refused.solutions == ()
    assert refused.diagnostics["satAdmitted"] is False


def test_missing_warship_pin_on_leave_signal_refuses_sat():
    admission = _admission(_warship_drop_signal(), pins=())
    assert admission.admitted is False
    assert admission.refused_class == "warship"


def test_unknown_class_signal_refuses_sat():
    admission = _admission(_unknown_class_signal(), pins=())
    assert admission.admitted is False
    assert admission.refused_class is None


def test_idle_dock_only_signal_without_scoreboard_drop_admits_sat():
    admission = _admission(
        CountLatticeSignal(
            events=(CountLatticeClassEvent(ship_class=None, source="idle_dock", count=1),)
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
    assert military_sat_refusal_result(admission) is None


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
    row = public_scoreboard_row_from_observation(observation)
    pairing = classify_public_scoreboard_pairing(
        row,
        (),
        settings=None,
        is_after_ship_limit=False,
    )
    idle_dock = transfer_budget_for_row(
        row,
        settings=None,
        is_after_ship_limit=False,
    )
    admission = resolve_military_sat_admission(
        observation,
        pairing=pairing,
        idle_dock=idle_dock,
        prior_ledger=_ledger(_singleton_unknown_hull_warship()),
        this_turn_ships=(),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert admission.admitted is False
    assert admission.refused_class == "warship"


def test_military_sat_refused_payload_is_incomplete_and_not_no_exact_solution():
    result = InferenceResult(
        status=STATUS_MILITARY_SAT_REFUSED,
        solutions=(),
        diagnostics={"reason": "unpinned_military_departure", "satAdmitted": False},
    )
    payload = inference_api_payload(
        status=result.status,
        summary=format_inference_summary(result),
        solutions=result.solutions,
        diagnostics=result.diagnostics,
    )
    assert payload["status"] == STATUS_MILITARY_SAT_REFUSED
    assert payload["status"] != STATUS_NO_EXACT_SOLUTION
    assert payload["isComplete"] is False
    assert payload["solutions"] == []
    assert "placeholders" not in payload
    assert "Unpinned military departure" in payload["summary"]
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


def test_unpinned_warship_drop_does_not_build_catalog_or_run_sat(sample_turn, monkeypatch):
    sat_calls: list = []
    catalog_calls: list = []

    def _catalog(*args, **kwargs):
        catalog_calls.append(1)
        raise AssertionError("military catalog must not be built")

    _patch_sat(monkeypatch, sat_calls)
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        _catalog,
    )
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    result, catalog, problem, attempted, _ = solve_with_policy_ladder(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        prior_fleet_records=(_singleton_unknown_hull_warship(),),
    )
    assert result.status == STATUS_MILITARY_SAT_REFUSED
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
    assert result.status != STATUS_MILITARY_SAT_REFUSED
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
    assert result.status != STATUS_MILITARY_SAT_REFUSED
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
    assert result.status != STATUS_MILITARY_SAT_REFUSED
    assert catalog is not None
    assert attempted
    assert sat_calls
