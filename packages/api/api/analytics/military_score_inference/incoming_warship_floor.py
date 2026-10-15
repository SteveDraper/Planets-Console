"""Incoming warship transfers scored by minimum legal hull fill.

When the catalog has no ship builds, each acquired-warship donor is a possible
transfer if some active known hull's minimum legal warship fill fits inside the
observed military rise. The remainder stays unexplained. Torpedo counts are not
fitted onto those ships.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from api.analytics.fleet.field_constraints import known_positive_component_id
from api.analytics.fleet.types import FleetShipRecord
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.concepts.hulls import is_unknown_military_ship_sentinel_hull_id
from api.concepts.ship_build_military import warship_construction_envelope_2x
from api.models.components import Beam, Engine, Hull, Torpedo

ACQUIRED_WARSHIP_ACTION_PREFIX = "acquired:warship:"
INCOMING_WARSHIP_FLOOR_STOP_REASON = "incoming_warship_floor"

CounterpartyFleetLoader = Callable[[int], tuple[FleetShipRecord, ...]]


def counterparty_fleet_loader(
    session: InferenceRowStreamSession,
) -> CounterpartyFleetLoader | None:
    """Load each donor's prior-turn active ships through fleet persistence.

    Returns None when this row has no query context, so the caller keeps the
    existing search.
    """
    query_context = session.query_context
    if query_context is None or session.turn_number <= 1:
        return None
    from api.analytics.scores.prior_fleet_resolution import fleet_compute_services

    services = fleet_compute_services(query_context)
    if services is None:
        return None
    game_id = session.game_id
    perspective = session.perspective
    prior_turn = session.turn_number - 1
    persistence = services.persistence

    def load(player_id: int) -> tuple[FleetShipRecord, ...]:
        persisted = persistence.get_ledger(game_id, perspective, prior_turn, player_id)
        if persisted is None:
            return ()
        return tuple(
            record for record in persisted.ledger.records if record.disposition == "active"
        )

    return load


def fitting_incoming_warship_transfers(
    *,
    military_delta_2x: int,
    warship_delta: int,
    actions: Sequence[CandidateAction],
    records_for_player: CounterpartyFleetLoader | None,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    max_solutions: int,
) -> tuple[InferenceSolution, ...] | None:
    """One transfer solution per donor whose hull floor fits the military rise.

    None means the caller should keep the existing search: no acquired warship,
    no donor ledger, or every known hull floor sits above the rise.
    """
    if (
        records_for_player is None
        or warship_delta <= 0
        or military_delta_2x <= 0
        or max_solutions <= 0
    ):
        return None
    acquired = [
        action
        for action in actions
        if action.warship_delta > 0
        and action.counterparty_player_id is not None
        and action.id.startswith(ACQUIRED_WARSHIP_ACTION_PREFIX)
    ]
    if not acquired:
        return None
    solutions: list[InferenceSolution] = []
    saw_donor_ships = False
    for action in sorted(acquired, key=lambda item: (item.counterparty_player_id or 0, item.id)):
        player_id = action.counterparty_player_id
        if player_id is None:
            continue
        records = records_for_player(player_id)
        if not records:
            continue
        saw_donor_ships = True
        if not _donor_hull_floor_fits(
            records,
            military_delta_2x=military_delta_2x,
            hulls_by_id=hulls_by_id,
            engines_by_id=engines_by_id,
            beams_by_id=beams_by_id,
            torpedos_by_id=torpedos_by_id,
        ):
            continue
        solutions.append(
            InferenceSolution(
                objective_value=0,
                actions=(
                    InferenceSolutionAction(
                        action_id=action.id,
                        label=action.label,
                        count=1,
                        counterparty_player_id=player_id,
                    ),
                ),
                ship_first_family="mine_overshoot",
            )
        )
        if len(solutions) >= max_solutions:
            break
    if not saw_donor_ships or not solutions:
        return None
    return tuple(solutions)


def _donor_hull_floor_fits(
    records: tuple[FleetShipRecord, ...],
    *,
    military_delta_2x: int,
    hulls_by_id: Mapping[int, Hull],
    engines_by_id: Mapping[int, Engine],
    beams_by_id: Mapping[int, Beam],
    torpedos_by_id: Mapping[int, Torpedo],
) -> bool:
    hull_tables = dict(hulls_by_id)
    engine_tables = dict(engines_by_id)
    beam_tables = dict(beams_by_id)
    torpedo_tables = dict(torpedos_by_id)
    for record in records:
        if record.disposition != "active":
            continue
        hull_id = known_positive_component_id(record.fields.hull)
        if hull_id is None or is_unknown_military_ship_sentinel_hull_id(hull_id):
            continue
        envelope = warship_construction_envelope_2x(
            hulls_by_id=hull_tables,
            engines_by_id=engine_tables,
            beams_by_id=beam_tables,
            torpedos_by_id=torpedo_tables,
            buildable_hull_ids=frozenset({hull_id}),
        )
        if envelope is None:
            continue
        if envelope[0] <= military_delta_2x:
            return True
    return False
