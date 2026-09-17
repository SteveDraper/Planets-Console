"""Case-2 emit: placeholder departures, unknown-loss leftover, lattice signatures.

In-memory product for refused military SAT (unpinned military-moving class).
Persist / stream / export of the status is phase 4. Contract: design §3.12.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetShipClass,
    FleetShipRecord,
)
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.count_lattice import (
    class_drops_from_observation,
    remainder_sets_after_alibi,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceResult
from api.analytics.military_score_inference.post_unsat_placeholders import (
    PLACEHOLDER_BUILD_SLOT_USAGE,
    UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
    post_unsat_placeholders,
)
from api.analytics.military_score_inference.prior_fleet_decrease_candidates import (
    option_set_envelope_2x,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    TransferBudget,
    public_scoreboard_row_from_observation,
    unique_incoming_class,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    LatticeSignature,
    PlaceholderBuild,
    PlaceholderDeparture,
    UnknownLossBoundLeftover,
    UnknownLossLeftover,
)
from api.concepts.hulls import (
    GENERIC_FREIGHTER_SENTINEL_HULL_ID,
    UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
)
from api.concepts.ship_build_military import warship_construction_envelope_2x
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.ship import Ship

STATUS_UNCHARACTERIZED_ROSTER = "uncharacterized_roster"
UNCHARACTERIZED_ROSTER_SUMMARY = "Uncharacterized roster"


@dataclass(frozen=True)
class UncharacterizedRosterProduct:
    placeholders: tuple[dict[str, object], ...]
    placeholder_departures: tuple[PlaceholderDeparture, ...]
    leftover: UnknownLossLeftover
    lattice_signatures: tuple[LatticeSignature, ...]


def unknown_loss_bound_2x(observed_drop_2x: int, max_possible_lost_construction_2x: int) -> int:
    """Lower bound on unexplained military in solver 2x units."""
    return max(0, observed_drop_2x - max_possible_lost_construction_2x)


def emit_uncharacterized_roster(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    idle_dock: TransferBudget | None,
    *,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> UncharacterizedRosterProduct:
    """Close the count / PP lattice without a military SAT catalog."""
    this_row = public_scoreboard_row_from_observation(observation)
    idle_class = unique_incoming_class(this_row)
    signatures = _lattice_signatures(
        idle_dock,
        idle_class=idle_class,
        pairing=pairing,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    hidden_builds = post_unsat_placeholders(
        observation,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    leftover = UnknownLossBoundLeftover(
        lower_bound_2x=unknown_loss_bound_2x(
            max(0, -observation.military_delta_2x),
            _max_possible_lost_construction_2x(
                observation,
                pairing,
                prior_ledger=prior_ledger,
                this_turn_ships=this_turn_ships,
                hulls_by_id=hulls_by_id,
                engines_by_id=engines_by_id,
                beams_by_id=beams_by_id,
                torpedos_by_id=torpedos_by_id,
                buildable_hull_ids=buildable_hull_ids,
            ),
        )
    )
    return UncharacterizedRosterProduct(
        placeholders=tuple(hidden_builds),
        placeholder_departures=_placeholder_departures(pairing, idle_dock, idle_class),
        leftover=leftover,
        lattice_signatures=signatures,
    )


def uncharacterized_roster_result(
    product: UncharacterizedRosterProduct,
    *,
    diagnostics: dict[str, object] | None = None,
) -> InferenceResult:
    """Solver-result shape for a case-2 emit. ``solutions[]`` stays empty."""
    return InferenceResult(
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solutions=(),
        diagnostics=dict(diagnostics or {}),
        placeholders=product.placeholders,
        placeholder_departures=product.placeholder_departures,
        leftover=product.leftover,
        lattice_signatures=product.lattice_signatures,
    )


def uncharacterized_roster_result_from_pairing(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    idle_dock: TransferBudget | None,
    turn: TurnInfo,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
    *,
    diagnostics: dict[str, object] | None = None,
) -> InferenceResult:
    """Emit the case-2 product from an already-classified pairing."""
    product = emit_uncharacterized_roster(
        observation,
        pairing,
        idle_dock,
        prior_ledger=FleetAcquisitionLedger(
            player_id=observation.player_id,
            records=list(prior_fleet_records),
        ),
        this_turn_ships=turn.ships,
        hulls_by_id={hull.id: hull for hull in turn.hulls},
        engines_by_id={engine.id: engine for engine in turn.engines},
        beams_by_id={beam.id: beam for beam in turn.beams},
        torpedos_by_id={torpedo.id: torpedo for torpedo in turn.torpedos},
        buildable_hull_ids=buildable_hull_ids_for_player(turn, observation.player_id),
    )
    return uncharacterized_roster_result(product, diagnostics=diagnostics)


def _placeholder_departures(
    pairing: PublicScoreboardPairing,
    idle_dock: TransferBudget | None,
    idle_class: FleetShipClass | None,
) -> tuple[PlaceholderDeparture, ...]:
    departures: list[PlaceholderDeparture] = []
    for match in pairing.matches:
        if match.family != "gift":
            continue
        if match.is_unpinned_class_choice():
            continue
        if match.warship_delta < 0:
            departures.append(
                PlaceholderDeparture(
                    ship_class="warship",
                    count=-match.warship_delta,
                    counterparty_player_id=match.counterparty_player_id,
                )
            )
        if match.freighter_delta < 0:
            departures.append(
                PlaceholderDeparture(
                    ship_class="freighter",
                    count=-match.freighter_delta,
                    counterparty_player_id=match.counterparty_player_id,
                )
            )
    if pairing.unmatched_warship_drop > 0:
        departures.append(
            PlaceholderDeparture(ship_class="warship", count=pairing.unmatched_warship_drop)
        )
    if pairing.unmatched_freighter_drop > 0:
        departures.append(
            PlaceholderDeparture(ship_class="freighter", count=pairing.unmatched_freighter_drop)
        )
    if (
        idle_dock is not None
        and idle_dock.excess_out > 0
        and idle_class is not None
        and not any(entry.ship_class == idle_class for entry in departures)
    ):
        departures.append(PlaceholderDeparture(ship_class=idle_class, count=idle_dock.excess_out))
    return tuple(departures)


def _lattice_signatures(
    idle_dock: TransferBudget | None,
    *,
    idle_class: FleetShipClass | None,
    pairing: PublicScoreboardPairing,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> tuple[LatticeSignature, ...]:
    if idle_dock is None or idle_class is not None:
        return ()
    build_count = idle_dock.implied_ships_built or 0
    departure_count = idle_dock.excess_out
    if build_count <= 0 or departure_count <= 0:
        return ()
    counterparty = _unknown_class_gift_counterparty(pairing)
    envelope = warship_construction_envelope_2x(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    return (
        LatticeSignature(
            ship_class="warship",
            build=_unknown_military_build(build_count, envelope),
            departure=PlaceholderDeparture(
                ship_class="warship",
                count=departure_count,
                counterparty_player_id=counterparty,
            ),
        ),
        LatticeSignature(
            ship_class="freighter",
            build=_generic_freighter_build(build_count),
            departure=PlaceholderDeparture(
                ship_class="freighter",
                count=departure_count,
                counterparty_player_id=counterparty,
            ),
        ),
    )


def _unknown_class_gift_counterparty(pairing: PublicScoreboardPairing) -> int | None:
    for match in pairing.matches:
        if match.family == "gift" and match.is_unpinned_class_choice():
            return match.counterparty_player_id
    return None


def _unknown_military_build(
    count: int,
    envelope: tuple[int, int] | None,
) -> PlaceholderBuild:
    min_2x, max_2x = (None, None) if envelope is None else envelope
    return PlaceholderBuild(
        id=UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
        hull_id=UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
        count=count,
        build_slot_usage=PLACEHOLDER_BUILD_SLOT_USAGE,
        military_score_delta_2x_min=min_2x,
        military_score_delta_2x_max=max_2x,
    )


def _generic_freighter_build(count: int) -> PlaceholderBuild:
    return PlaceholderBuild(
        id=GENERIC_FREIGHTER_COMBO_ID,
        hull_id=GENERIC_FREIGHTER_SENTINEL_HULL_ID,
        count=count,
        build_slot_usage=PLACEHOLDER_BUILD_SLOT_USAGE,
    )


def _unpinned_military_count(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
) -> int:
    for match in pairing.matches:
        if match.family == "gift" and match.is_unpinned_class_choice():
            return match.transfer_count
    if pairing.unmatched_warship_drop > 0:
        return pairing.unmatched_warship_drop
    return max(0, -observation.warship_delta)


def _max_possible_lost_construction_2x(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    *,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> int:
    count = _unpinned_military_count(observation, pairing)
    remainder_maxes = _same_class_remainder_envelope_maxes(
        observation,
        prior_ledger,
        this_turn_ships,
        hulls_by_id=hulls_by_id,
        ship_class="warship",
    )
    if remainder_maxes:
        ranked = sorted(remainder_maxes, reverse=True)
        return sum(ranked[:count]) if count > 0 else 0
    envelope = warship_construction_envelope_2x(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    race_max = 0 if envelope is None else envelope[1]
    return race_max * count


def _same_class_remainder_envelope_maxes(
    observation: InferenceObservation,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    *,
    hulls_by_id: dict[int, Hull],
    ship_class: FleetShipClass,
) -> tuple[int, ...]:
    remainder_sets = remainder_sets_after_alibi(
        observation.player_id,
        prior_ledger,
        this_turn_ships,
        class_drops_from_observation(observation),
        hulls_by_id=hulls_by_id,
    )
    maxes: list[int] = []
    for remainder_set in remainder_sets:
        if remainder_set.ship_class != ship_class:
            continue
        for record in remainder_set.remainders:
            envelope = option_set_envelope_2x(record.build_option_sets)
            if envelope is not None:
                maxes.append(envelope[1])
    return tuple(maxes)
