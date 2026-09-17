"""Case-2 emit: placeholder departures, unknown-loss leftover, lattice signatures."""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetShipRecord,
)
from api.analytics.military_score_inference.inference_api_payload import (
    format_inference_summary,
    inference_api_payload,
    product_payload_fields,
)
from api.analytics.military_score_inference.military_sat_admission import (
    military_sat_refusal_from_turn,
    resolve_military_sat_admission,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceResult
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.post_unsat_placeholders import (
    UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
    emit_uncharacterized_roster,
    uncharacterized_roster_result,
    unknown_loss_bound_2x,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    LatticeSignature,
    PlaceholderBuild,
    PlaceholderDeparture,
    PointLeftover,
    UnknownLossBoundLeftover,
)
from api.analytics.scores.export_wire import product_fields_from_wire_complete
from api.concepts.hulls import UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
from api.serialization.uncharacterized_roster import (
    PLACEHOLDER_DEPARTURE_ID,
    UncharacterizedRosterCodecError,
    lattice_signature_from_json,
    lattice_signature_to_json,
    leftover_from_json,
    leftover_to_json,
    placeholder_departure_from_json,
    placeholder_departure_to_json,
)

from tests.fixtures.military_score_inference import _observation, without_player_minefields
from tests.fixtures.pp_gap_transfer import birds_row
from tests.fixtures.ship_transfer_families import (
    _class_only_freighter_record,
    _peer_row,
    _scoreboard_class_event,
    _singleton_unknown_hull_warship,
)


def _observation_from_row(row) -> InferenceObservation:
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


def _emit(observation, catalog, *, records=(), peer_rows=(), settings=None):
    pairing, idle_dock = _pairing_and_idle_dock(observation, peer_rows=peer_rows, settings=settings)
    return emit_uncharacterized_roster(
        observation,
        pairing,
        idle_dock,
        prior_ledger=FleetAcquisitionLedger(
            player_id=observation.player_id,
            records=list(records),
        ),
        this_turn_ships=(),
        hulls_by_id=catalog["hulls_by_id"],
        engines_by_id=catalog["engines_by_id"],
        beams_by_id=catalog["beams_by_id"],
        torpedos_by_id=catalog["torpedos_by_id"],
        buildable_hull_ids=catalog["buildable_hull_ids"],
    )


def _envelope_warship(*, max_2x: int) -> FleetShipRecord:
    return FleetShipRecord(
        record_id="envelope-warship",
        events=[_scoreboard_class_event("warship")],
        build_option_sets=[
            FleetBuildOptionSet(
                military_score_delta_2x_min=0,
                military_score_delta_2x_max=max_2x,
            )
        ],
    )


def _departures(placeholders) -> list[dict[str, object]]:
    return [entry for entry in placeholders if entry.get("id") == PLACEHOLDER_DEPARTURE_ID]


def _payload_from_result(result: InferenceResult) -> dict[str, object]:
    return inference_api_payload(
        status=result.status,
        summary=format_inference_summary(result),
        solutions=result.solutions,
        diagnostics=result.diagnostics,
        placeholders=list(result.placeholders),
        leftover=result.leftover,
        placeholder_departures=result.placeholder_departures,
        lattice_signatures=result.lattice_signatures,
    )


def _peer_score(sample_turn, *, ownerid: int, shipchange: int, militarychange: int):
    return replace(
        sample_turn.scores[0],
        ownerid=ownerid,
        shipchange=shipchange,
        freighterchange=0,
        militarychange=militarychange,
        planetchange=0,
        starbasechange=0,
    )


def test_unknown_loss_bound_arithmetic():
    assert unknown_loss_bound_2x(1000, 200) == 800
    assert unknown_loss_bound_2x(1000, 1000) == 0
    assert unknown_loss_bound_2x(1000, 2000) == 0


def test_net_minus_one_warship_unpinned_emits_departure_and_bound(
    sample_turn, synthetic_catalog_context
):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    product = _emit(
        observation,
        synthetic_catalog_context,
        records=(_singleton_unknown_hull_warship(),),
    )
    departures = product.placeholder_departures
    assert product.leftover.kind == "unknown_loss_bound"
    assert isinstance(product.leftover, UnknownLossBoundLeftover)
    assert len(departures) == 1
    assert departures[0].ship_class == "warship"
    assert departures[0].count == 1
    assert departures[0].counterparty_player_id is None
    assert product.lattice_signatures == ()

    result = military_sat_refusal_from_turn(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        (_singleton_unknown_hull_warship(),),
    )
    assert result is not None
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert result.solutions == ()
    assert isinstance(result.leftover, UnknownLossBoundLeftover)
    payload = _payload_from_result(uncharacterized_roster_result(product))
    wire_departures = _departures(payload["placeholders"])
    assert payload["solutions"] == []
    assert payload["leftover"]["kind"] == "unknown_loss_bound"
    assert "unexplainedMilitaryDelta2x" not in payload
    assert len(wire_departures) == 1
    assert wire_departures[0]["shipClass"] == "warship"
    assert "hullId" not in wire_departures[0]
    assert "militaryScoreDelta2xMin" not in wire_departures[0]
    assert all("objectiveValue" not in entry for entry in payload["latticeSignatures"])


def test_bound_from_remainder_envelopes(synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-1000)
    product = _emit(
        observation,
        synthetic_catalog_context,
        records=(_envelope_warship(max_2x=200),),
    )
    assert product.leftover == UnknownLossBoundLeftover(lower_bound_2x=800)

    zero_bound = _emit(
        observation,
        synthetic_catalog_context,
        records=(_envelope_warship(max_2x=2000),),
    )
    assert zero_bound.leftover == UnknownLossBoundLeftover(lower_bound_2x=0)
    assert zero_bound.leftover.kind == "unknown_loss_bound"


def test_idle_dock_k1_net0_emits_both_lattice_signatures(sample_turn):
    observation = _observation_from_row(birds_row())
    result = military_sat_refusal_from_turn(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
    )
    assert result is not None
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert result.solutions == ()
    assert result.diagnostics["satAdmitted"] is False
    assert [entry.ship_class for entry in result.lattice_signatures] == [
        "warship",
        "freighter",
    ]
    assert all(isinstance(entry.build, PlaceholderBuild) for entry in result.lattice_signatures)
    payload = _payload_from_result(result)
    assert payload["solutions"] == []
    assert "objectiveValue" not in payload
    assert len(payload["latticeSignatures"]) == 2
    for entry in payload["latticeSignatures"]:
        assert "objectiveValue" not in entry
        assert entry["build"]["count"] == 1
        assert entry["departure"]["count"] == 1
        assert entry["departure"]["shipClass"] == entry["shipClass"]
    assert result.placeholder_departures == ()
    assert _departures(result.placeholders) == []


def test_gift_counterparty_on_placeholder_and_no_sat(sample_turn, synthetic_catalog_context):
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    peer = _peer_row(3, warship=1, military_2x=40)
    pairing, idle_dock = _pairing_and_idle_dock(observation, peer_rows=(peer,))
    assert pairing.matches[0].family == "gift"
    admission = resolve_military_sat_admission(
        observation,
        pairing=pairing,
        idle_dock=idle_dock,
        prior_ledger=FleetAcquisitionLedger(
            player_id=observation.player_id,
            records=[_singleton_unknown_hull_warship()],
        ),
        this_turn_ships=(),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert admission.admitted is False

    turn = replace(
        without_player_minefields(sample_turn, observation.player_id),
        scores=(_peer_score(sample_turn, ownerid=3, shipchange=1, militarychange=20),),
    )
    result = military_sat_refusal_from_turn(
        observation,
        turn,
        (_singleton_unknown_hull_warship(),),
    )
    assert result is not None
    assert result.status == STATUS_UNCHARACTERIZED_ROSTER
    assert result.solutions == ()
    assert len(result.placeholder_departures) == 1
    assert result.placeholder_departures[0].count == 1
    assert result.placeholder_departures[0].ship_class == "warship"
    assert result.placeholder_departures[0].counterparty_player_id == 3
    payload = _payload_from_result(result)
    departures = _departures(payload["placeholders"])
    assert len(departures) == 1
    assert departures[0]["counterpartyPlayerId"] == 3


def test_freighter_only_unpin_keeps_point_leftover(sample_turn, monkeypatch):
    sat_calls: list = []

    def _solve(problem, **kwargs):
        sat_calls.append(problem)
        return InferenceResult(status="exact", solutions=(), diagnostics={})

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.leftover_0_solutions",
        lambda solutions, *_args, **_kwargs: list(solutions),
    )
    observation = _observation(warship_delta=0, freighter_delta=-1, military_delta_2x=22)
    result, catalog, _problem, attempted, _ = solve_with_policy_ladder(
        observation,
        without_player_minefields(sample_turn, observation.player_id),
        prior_fleet_records=(_class_only_freighter_record(),),
    )
    assert result.status != STATUS_UNCHARACTERIZED_ROSTER
    assert catalog is not None
    assert attempted
    assert sat_calls
    payload = inference_api_payload(
        status="moderate_residual",
        summary=format_inference_summary(
            InferenceResult(status="moderate_residual", solutions=(), diagnostics={})
        ),
        solutions=(),
        diagnostics={},
        observation=observation,
        placeholders=[],
        unexplained_military_delta_2x=observation.military_delta_2x,
    )
    assert payload["unexplainedMilitaryDelta2x"] == 22
    assert "leftover" not in payload


def test_unknown_military_ship_stays_positive_count(synthetic_catalog_context):
    drop = _emit(
        _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40),
        synthetic_catalog_context,
        records=(_singleton_unknown_hull_warship(),),
    )
    assert all(
        entry.get("id") != UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID for entry in drop.placeholders
    )
    assert all(
        not (
            entry.get("hullId") == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
            and isinstance(entry.get("count"), int)
            and entry["count"] <= 0
        )
        for entry in drop.placeholders
    )

    hidden_build = emit_uncharacterized_roster(
        _observation(warship_delta=1, freighter_delta=0, military_delta_2x=40),
        PublicScoreboardPairing(
            matches=(),
            unmatched_warship_drop=0,
            unmatched_freighter_drop=0,
        ),
        None,
        prior_ledger=FleetAcquisitionLedger(player_id=8, records=[]),
        this_turn_ships=(),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
    )
    builds = [
        entry
        for entry in hidden_build.placeholders
        if entry.get("id") == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
    ]
    assert len(builds) == 1
    assert builds[0]["count"] > 0


def test_leftover_codec_does_not_encode_bound_as_point():
    bound = UnknownLossBoundLeftover(lower_bound_2x=800)
    wire = leftover_to_json(bound)
    assert wire == {"kind": "unknown_loss_bound", "lowerBound2x": 800}
    assert "unexplainedMilitaryDelta2x" not in wire
    assert leftover_from_json(wire) == bound
    point = PointLeftover(unexplained_military_delta_2x=22)
    assert leftover_from_json(leftover_to_json(point)) == point
    with pytest.raises(UncharacterizedRosterCodecError, match="unexplainedMilitaryDelta2x"):
        leftover_from_json(
            {
                "kind": "unknown_loss_bound",
                "lowerBound2x": 800,
                "unexplainedMilitaryDelta2x": 800,
            }
        )


def test_placeholder_departure_codec_round_trip():
    departure = PlaceholderDeparture(
        ship_class="warship",
        count=2,
        counterparty_player_id=5,
    )
    wire = placeholder_departure_to_json(departure)
    assert wire["id"] == PLACEHOLDER_DEPARTURE_ID
    assert "hullId" not in wire
    assert placeholder_departure_from_json(wire) == departure


def test_lattice_signature_codec_round_trip():
    signature = LatticeSignature(
        ship_class="warship",
        build=PlaceholderBuild(
            id=UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
            hull_id=UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
            count=1,
            build_slot_usage=1,
            military_score_delta_2x_min=0,
            military_score_delta_2x_max=40,
        ),
        departure=PlaceholderDeparture(ship_class="warship", count=1),
    )
    wire = lattice_signature_to_json(signature)
    assert "objectiveValue" not in wire
    assert wire["build"]["hullId"] == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
    assert lattice_signature_from_json(wire) == signature
    with pytest.raises(UncharacterizedRosterCodecError, match="objectiveValue"):
        lattice_signature_from_json({**wire, "objectiveValue": 1})


def test_product_payload_fields_omits_point_leftover_for_roster():
    product = product_payload_fields(STATUS_UNCHARACTERIZED_ROSTER, leftover=22)
    assert product.status == STATUS_UNCHARACTERIZED_ROSTER
    assert product.placeholders == []
    assert product.unexplained_military_delta_2x is None
    assert product.leftover is None
    assert product.lattice_signatures is None


def test_wire_complete_reconstruction_keeps_roster_leftover_and_signatures():
    reconstructed = product_fields_from_wire_complete(
        {
            "status": STATUS_UNCHARACTERIZED_ROSTER,
            "leftover": {"kind": "unknown_loss_bound", "lowerBound2x": 800},
            "latticeSignatures": [
                {
                    "shipClass": "warship",
                    "build": {"id": "unknown_military_ship", "count": 1},
                    "departure": {
                        "id": PLACEHOLDER_DEPARTURE_ID,
                        "shipClass": "warship",
                        "count": 1,
                    },
                }
            ],
            "placeholders": [],
            "unexplainedMilitaryDelta2x": 22,
        }
    )
    assert reconstructed.status == STATUS_UNCHARACTERIZED_ROSTER
    assert reconstructed.unexplained_military_delta_2x is None
    assert reconstructed.leftover == {"kind": "unknown_loss_bound", "lowerBound2x": 800}
    assert reconstructed.lattice_signatures is not None
    assert reconstructed.lattice_signatures[0]["shipClass"] == "warship"
