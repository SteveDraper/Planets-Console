"""Prefix step: admit fitting incoming-warship transfers on an empty ship catalog.

The step reports an outcome. It updates the hold lists it is given and leaves
ladder status, the unsolved problem, and step diagnostics to the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.fleet.types import CounterpartyFleetLoader
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.incoming_warship_floor import (
    INCOMING_WARSHIP_FLOOR_STOP_REASON,
    fitting_incoming_warship_transfers,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    solution_signature,
)
from api.analytics.military_score_inference.ship_first_family import (
    admit_ship_first_ranked_solution,
)
from api.analytics.military_score_inference.ship_first_overshoot import (
    CatalogScoreLookups,
    ShipFirstOvershootPlan,
    leftover_military_2x,
)
from api.concepts.turn_component_catalog import turn_component_indexes
from api.models.game import TurnInfo


@dataclass(frozen=True, slots=True)
class FloorOutcome:
    """Transfers admitted for an empty ship-build catalog.

    ``closes_tier`` is true when at least one transfer entered the hold.
    """

    admitted: tuple[InferenceSolution, ...]

    @property
    def closes_tier(self) -> bool:
        return bool(self.admitted)


def incoming_warship_floor_diagnostics(held_solution_count: int) -> dict[str, object]:
    """Diagnostics recorded when the floor closes the tier without a solve."""
    return {
        "stopped_reason": INCOMING_WARSHIP_FLOOR_STOP_REASON,
        "structural_hit_count": held_solution_count,
        "deterministicTime": 0.0,
        "solveWallSeconds": 0.0,
    }


def consider_incoming_warship_floor(
    *,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    turn: TurnInfo,
    overlay: ShipFirstOvershootPlan | None,
    score_lookups: CatalogScoreLookups,
    records_for_player: CounterpartyFleetLoader | None,
    merged_solutions: list[InferenceSolution],
    seen_signatures: set[SolutionSignature],
    overshoot_signatures: set[SolutionSignature],
    newly_admitted: list[InferenceSolution],
    max_solutions: int,
    on_admitted: Callable[[InferenceSolution], None] | None,
) -> FloorOutcome:
    """Admit fitting donor transfers when this catalog has no ship builds.

    A catalog that already has build explanations, or a row with no fitting
    donor, returns an empty outcome so the caller keeps the overshoot search.
    """
    if overlay is None or catalog.ship_build_combos:
        return FloorOutcome(())
    indexes = turn_component_indexes(turn)
    solutions = fitting_incoming_warship_transfers(
        military_delta_2x=observation.military_delta_2x,
        warship_delta=observation.warship_delta,
        actions=catalog.aggregate_actions,
        records_for_player=records_for_player,
        hulls_by_id=indexes.hulls_by_id,
        engines_by_id=indexes.engines_by_id,
        beams_by_id=indexes.beams_by_id,
        torpedos_by_id=indexes.torpedos_by_id,
        max_solutions=max_solutions,
    )
    if not solutions:
        return FloorOutcome(())

    def leftover_2x(held: InferenceSolution) -> int:
        return leftover_military_2x(held, observation, score_lookups)

    admitted: list[InferenceSolution] = []
    for solution in solutions:
        if not admit_ship_first_ranked_solution(
            merged_solutions,
            seen_signatures,
            solution,
            max_solutions=max_solutions,
            leftover_2x=leftover_2x,
            on_admitted=on_admitted,
        ):
            continue
        newly_admitted.append(solution)
        overshoot_signatures.add(solution_signature(solution))
        admitted.append(solution)
    return FloorOutcome(tuple(admitted))
