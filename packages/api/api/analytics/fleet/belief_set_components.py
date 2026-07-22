"""Shared belief-set component id union for fleet ship records."""

from __future__ import annotations

from collections.abc import Iterable

from api.analytics.fleet.field_constraints import known_positive_component_id
from api.analytics.fleet.option_set_mass import row_option_set_softmax_probabilities
from api.analytics.fleet.types import FleetBuildOptionSet, FleetShipRecord

OPTION_SET_COMPONENT_ATTRS: dict[str, str] = {
    "hull": "hull_id",
    "engine": "engine_id",
    "beams": "beam_id",
    "launchers": "torp_id",
}

LAUNCHERS_AXIS_FIELD_NAME = "launchers"


def positive_option_component_id(option_set: FleetBuildOptionSet, attr: str) -> int | None:
    raw = getattr(option_set, attr)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        return None
    return raw


def component_ids_for_record_on_axis(
    record: FleetShipRecord,
    axis_field_name: str,
    *,
    option_set_mass_threshold: float | None = None,
) -> set[int]:
    """Belief-set ids for one axis: known field plus build option sets.

    When ``option_set_mass_threshold`` is set, only option sets whose per-row
    softmax probability meets that floor contribute (known ids always count).
    When omitted, every option set contributes (flat admission union).
    """
    ids: set[int] = set()
    field = getattr(record.fields, axis_field_name)
    known_id = known_positive_component_id(field)
    if known_id is not None:
        ids.add(known_id)
    option_attr = OPTION_SET_COMPONENT_ATTRS[axis_field_name]
    if option_set_mass_threshold is None:
        for option_set in record.build_option_sets:
            option_id = positive_option_component_id(option_set, option_attr)
            if option_id is not None:
                ids.add(option_id)
        return ids

    probabilities = row_option_set_softmax_probabilities(record)
    for option_set, probability in zip(record.build_option_sets, probabilities, strict=True):
        if probability < option_set_mass_threshold:
            continue
        option_id = positive_option_component_id(option_set, option_attr)
        if option_id is not None:
            ids.add(option_id)
    return ids


def component_ids_for_axis_from_records(
    records: Iterable[FleetShipRecord],
    axis_field_name: str,
    *,
    active_only: bool = True,
    option_set_mass_threshold: float | None = None,
) -> set[int]:
    """Union component ids for one axis across fleet records."""
    ids: set[int] = set()
    for record in records:
        if active_only and record.disposition != "active":
            continue
        ids.update(
            component_ids_for_record_on_axis(
                record,
                axis_field_name,
                option_set_mass_threshold=option_set_mass_threshold,
            )
        )
    return ids


def launcher_component_ids_from_records(
    records: Iterable[FleetShipRecord],
) -> frozenset[int]:
    """Union launcher/torp ids from active records' known fields and build option sets."""
    return frozenset(
        component_ids_for_axis_from_records(records, LAUNCHERS_AXIS_FIELD_NAME),
    )
