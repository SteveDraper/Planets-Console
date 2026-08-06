"""Display-default build option set selection for fleet records."""

from __future__ import annotations

from api.analytics.fleet.types import FleetBuildOptionSet, FleetShipRecord


def resolve_display_default_build_option_set(
    record: FleetShipRecord,
) -> FleetBuildOptionSet | None:
    """Display-default option set: explicit index, else highest solution rank weight."""
    option_sets = record.build_option_sets
    if not option_sets:
        return None
    index = record.display_default_option_set_index
    if index is not None and 0 <= index < len(option_sets):
        return option_sets[index]
    best_index = 0
    best_weight = option_sets[0].solution_rank_weight
    for candidate_index, option_set in enumerate(option_sets[1:], start=1):
        if option_set.solution_rank_weight > best_weight:
            best_weight = option_set.solution_rank_weight
            best_index = candidate_index
    return option_sets[best_index]
