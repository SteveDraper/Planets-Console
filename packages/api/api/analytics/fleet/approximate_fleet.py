"""Approximate fleet ledger and the terminal scoreboard replacement.

One writer for both backfill settings. The observation persist copies the prior
ledger, matches this turn's visible ships, and saves that player's fleet file.
A terminal same-turn scoreboard result replaces the file. A missing prior is
an empty ledger and is not created.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from api.analytics.fleet.compute_plane.turn_delta import copy_prior_for_approximate
from api.analytics.fleet.id_bound_ingest import tighten_inferred_ship_id_bounds_if_computable
from api.analytics.fleet.materialization_provenance import resolve_fleet_materialization_provenance
from api.analytics.fleet.observation_ingest import (
    apply_id_bounds_then_observations,
    ingest_player_ship_observations,
)
from api.analytics.fleet.scoreboard_ship_totals import iter_current_turn_scores
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetCountDiscrepancy,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
    from api.analytics.fleet.persistence import FleetSnapshotPersistenceService


def approximate_fleet_ledger(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    perspective: int,
    turn_context: FleetTurnContext | None = None,
) -> FleetAcquisitionLedger:
    """Prior copy plus this turn's sightings. No inferred acquisitions or count collapse."""
    ledger = copy_prior_for_approximate(prior_ledger, turn)
    resolved_context = (
        turn_context if turn_context is not None else FleetTurnContext.from_turn(turn)
    )
    tighten_inferred_ship_id_bounds_if_computable(ledger, resolved_context)
    ingest_player_ship_observations(ledger, resolved_context, perspective=perspective)
    record_surplus_count_discrepancy(ledger, turn)
    return ledger


def terminal_fleet_ledger(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    inference_materialization: FleetInferenceMaterialization | None,
    turn_context: FleetTurnContext | None = None,
) -> FleetAcquisitionLedger:
    """Fold a terminal scoreboard into the prior, match sightings, then collapse."""
    from api.analytics.fleet.inferred_acquisition_ingest import ingest_player_inferred_acquisitions

    ledger = copy_prior_for_approximate(prior_ledger, turn)
    ingest_player_inferred_acquisitions(
        ledger,
        turn,
        game_id=game_id,
        perspective=perspective,
        inference_materialization=inference_materialization,
    )
    resolved_context = (
        turn_context if turn_context is not None else FleetTurnContext.from_turn(turn)
    )
    apply_id_bounds_then_observations(
        ledger,
        resolved_context,
        perspective=perspective,
    )
    record_surplus_count_discrepancy(ledger, turn)
    return ledger


def fleet_ledger_after_prior(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    prior_is_ensure_final: bool,
    game_id: int,
    perspective: int,
    player_id: int,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
    turn_context: FleetTurnContext | None = None,
) -> tuple[FleetAcquisitionLedger, FleetMaterializationProvenance]:
    """Approximate copy, or the terminal replacement when this turn's scoreboard is closed."""
    resolved_context = (
        turn_context if turn_context is not None else FleetTurnContext.from_turn(turn)
    )
    provenance = resolve_fleet_materialization_provenance(
        materialize_turn=turn.settings.turn,
        prior_is_ensure_final=prior_is_ensure_final,
        turn_context=resolved_context,
        player_id=player_id,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )
    if provenance.turn_evidence_at_n:
        ledger = terminal_fleet_ledger(
            prior_ledger,
            turn,
            game_id=game_id,
            perspective=perspective,
            inference_materialization=inference_materialization,
            turn_context=resolved_context,
        )
        return ledger, provenance
    ledger = approximate_fleet_ledger(
        prior_ledger,
        turn,
        perspective=perspective,
        turn_context=resolved_context,
    )
    return ledger, FleetMaterializationProvenance(
        turn_evidence_at_n=False,
        prior_ledger_at_n_minus_1=provenance.prior_ledger_at_n_minus_1,
    )


def record_surplus_count_discrepancy(
    ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
) -> None:
    """Set a discrepancy only when the columns imply fewer active ships than the roster.

    A shortfall or a missing score row leaves the field unset. The call drops
    whatever discrepancy the copied prior carried.
    """
    ledger.discrepancy = None
    score = next(
        (row for row in iter_current_turn_scores(turn) if row.ownerid == ledger.player_id),
        None,
    )
    if score is None:
        return
    implied = score.capitalships + score.freighters
    active = sum(1 for record in ledger.records if record.disposition == "active")
    if active > implied:
        ledger.discrepancy = FleetCountDiscrepancy(
            host_turn=turn.settings.turn,
            active_row_count=active,
            scoreboard_implied_count=implied,
        )


def refresh_following_approximate_fleets(
    *,
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    saved_turn: int,
    player_invalidation_generation: int,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
) -> None:
    """Replace each later approximate file from the ledger just saved.

    ``player_invalidation_generation`` is the epoch captured for the save that
    started this walk. The walk stops when that epoch no longer matches, and
    when it hits a missing file, an ensure-final ledger, or an eliminated
    player. A stop does not raise and does not roll back puts already stored.
    Does not create the missing turn. A terminal same-turn scoreboard writes
    the replacement; otherwise the copy stays approximate.
    """
    from api.analytics.fleet.eliminated_player import fleet_player_eliminated_at_turn
    from api.analytics.fleet.fleet_table_stream_scheduler import publish_saved_host_turn_ledger

    next_turn = saved_turn + 1
    while True:
        if (
            persistence.player_invalidation_generation(game_id, perspective, player_id)
            != player_invalidation_generation
        ):
            return
        existing = persistence.get_ledger(game_id, perspective, next_turn, player_id)
        if existing is None or existing.provenance.eliminated_at_turn:
            return
        if persistence.ledger_is_ensure_final(
            game_id,
            perspective,
            next_turn,
            player_id,
            existing,
        ):
            return
        turn = load_turn(next_turn)
        if turn is None or fleet_player_eliminated_at_turn(turn, player_id):
            return
        prior = persistence.get_ledger(game_id, perspective, next_turn - 1, player_id)
        if prior is None:
            return
        prior_is_ensure_final = persistence.ledger_is_ensure_final(
            game_id,
            perspective,
            next_turn - 1,
            player_id,
            prior,
        )
        ledger, provenance = fleet_ledger_after_prior(
            prior.ledger,
            turn,
            prior_is_ensure_final=prior_is_ensure_final,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
        )
        put_result = persistence.put_ledger(
            game_id,
            perspective,
            next_turn,
            player_id,
            PersistedFleetLedger(ledger=ledger, provenance=provenance),
        )
        publish_saved_host_turn_ledger(
            game_id=game_id,
            perspective=perspective,
            turn_number=next_turn,
            player_id=player_id,
            persisted=put_result.stored,
        )
        next_turn += 1
