"""Shared helpers for fleet field constraint interpretation."""

from __future__ import annotations

from api.analytics.fleet.types import FleetFieldConstraint, FleetFieldKnown


def known_positive_component_id(field: FleetFieldConstraint) -> int | None:
    if not isinstance(field, FleetFieldKnown):
        return None
    value = field.value
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value
