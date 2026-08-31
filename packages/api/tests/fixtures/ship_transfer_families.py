"""Shared record builders and catalog helpers for ship transfer family tests (#370)."""

from dataclasses import replace

from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    ShipTransferCatalogFragment,
    build_ship_transfer_catalog_fragment,
)
from api.concepts.hulls import UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
from api.concepts.ship_build_military import ship_build_military_score_delta_2x
from tests.fixtures.military_score_inference import _observation


def _scoreboard_class_event(ship_class: str) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=f"delta-{ship_class}",
        kind="scoreboard_delta",
        turn=110,
        source="scoreboard",
        payload={"shipClass": ship_class},
    )


def _known_warship_record(
    synthetic_catalog_context,
    *,
    beam_count: int = 2,
    record_id: str = "known-serpent",
) -> tuple[FleetShipRecord, int]:
    hull = synthetic_catalog_context["hulls_by_id"][24]
    engine = synthetic_catalog_context["engines_by_id"][1]
    beam = synthetic_catalog_context["beams_by_id"][1]
    military_2x = ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        None,
        beam_count=beam_count,
        launcher_count=0,
    )
    record = FleetShipRecord(
        record_id=record_id,
        fields=FleetShipRecordFields(
            hull=FleetFieldKnown(24),
            engine=FleetFieldKnown(1),
            beams=FleetFieldKnown(1),
            launchers=FleetFieldKnown(0),
        ),
        build_option_sets=[
            FleetBuildOptionSet(
                hull_id=24,
                engine_id=1,
                beam_id=1,
                beam_count=beam_count,
                launcher_count=0,
            )
        ],
    )
    return record, military_2x


def _envelope_warship_record() -> FleetShipRecord:
    return FleetShipRecord(
        record_id="envelope-warship",
        events=[_scoreboard_class_event("warship")],
        build_option_sets=[
            FleetBuildOptionSet(
                military_score_delta_2x_min=20,
                military_score_delta_2x_max=80,
            )
        ],
    )


def _class_only_warship_record() -> FleetShipRecord:
    return FleetShipRecord(
        record_id="class-only-warship",
        events=[_scoreboard_class_event("warship")],
    )


def _unknown_hull_envelope_warship_record() -> FleetShipRecord:
    return FleetShipRecord(
        record_id="unknown-hull-envelope",
        events=[_scoreboard_class_event("warship")],
        build_option_sets=[
            FleetBuildOptionSet(
                hull_id=UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
                military_score_delta_2x_min=20,
                military_score_delta_2x_max=80,
            )
        ],
    )


def _class_only_freighter_record() -> FleetShipRecord:
    return FleetShipRecord(
        record_id="class-only-freighter",
        events=[_scoreboard_class_event("freighter")],
    )


def _peer_row(
    player_id: int,
    *,
    warship: int,
    military_2x: int,
    freighter: int = 0,
) -> PublicScoreboardRow:
    return PublicScoreboardRow(
        player_id=player_id,
        warship_delta=warship,
        freighter_delta=freighter,
        military_delta_2x=military_2x,
    )


def _transfer_catalog_kwargs(synthetic_catalog_context) -> dict:
    return {
        "hulls_by_id": synthetic_catalog_context["hulls_by_id"],
        "engines_by_id": synthetic_catalog_context["engines_by_id"],
        "beams_by_id": synthetic_catalog_context["beams_by_id"],
        "torpedos_by_id": synthetic_catalog_context["torpedos_by_id"],
    }


def _class_flip_trade_catalog(
    synthetic_catalog_context,
    *,
    first_beam_count: int = 1,
    matching_beam_count: int = 2,
) -> tuple[InferenceObservation, ShipTransferCatalogFragment, int, int]:
    first, first_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=first_beam_count,
        record_id="serpent-first",
    )
    matching, matching_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=matching_beam_count,
        record_id="serpent-matching",
    )
    assert first_military != matching_military
    observation = replace(
        _observation(
            military_delta_2x=-matching_military,
            warship_delta=-1,
            freighter_delta=1,
        ),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=1, freighter=-1, military_2x=matching_military),),
        prior_fleet_records=(first, matching),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    return observation, fragment, first_military, matching_military


def _same_class_swap_catalog(
    synthetic_catalog_context,
    *,
    swap_military_2x: int = 40,
) -> tuple[InferenceObservation, ShipTransferCatalogFragment]:
    first, first_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=1,
        record_id="serpent-first",
    )
    second, second_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=2,
        record_id="serpent-second",
    )
    assert first_military != second_military
    observation = _observation(
        military_delta_2x=swap_military_2x,
        warship_delta=0,
        freighter_delta=0,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=0, military_2x=-swap_military_2x),),
        prior_fleet_records=(first, second),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    return observation, fragment


def _two_ship_class_flip_trade_fragment(
    synthetic_catalog_context,
    prior_fleet_records: tuple[FleetShipRecord, ...],
    *,
    military_delta_2x: int,
) -> tuple[InferenceObservation, ShipTransferCatalogFragment]:
    observation = replace(
        _observation(
            military_delta_2x=military_delta_2x,
            warship_delta=-2,
            freighter_delta=2,
        ),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=2, freighter=-2, military_2x=-military_delta_2x),),
        prior_fleet_records=prior_fleet_records,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    return observation, fragment
