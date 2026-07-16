"""Honest fleet materialization provenance from actual materialization inputs.

Provenance resolution assumes turn-N fleet evidence deltas are already applied
for the player ledger being persisted; see ``resolve_fleet_materialization_provenance``.
"""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.export_types import ExportScope
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.scores.export_precedence import (
    ScoresExportResolutionContext,
    is_scores_export_turn_evidence_closed_from_snapshot,
)
from api.analytics.scores.export_snapshot import (
    gather_scores_materialization_probe_snapshot,
)
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import TurnInfo
from api.serialization.inference_row_persistence import PersistedInferenceRow


def resolve_fleet_materialization_provenance(
    *,
    materialize_turn: int,
    prior_persisted: PersistedFleetLedger | None,
    turn_context: FleetTurnContext,
    player_id: int,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
) -> FleetMaterializationProvenance:
    """Set provenance flags from legs actually closed at write time.

    Caller contract: apply turn-*N* fleet evidence deltas for ``player_id``
    (scoreboard ingest, ship sightings, ship-id bound tightening, and optional
    scores refinement, e.g. via ``apply_fleet_turn_delta_for_player``) before
    calling this function. ``turnEvidenceAtN`` checks RST@*N* availability and
    terminal ``scores@N`` evidence for this player (not merely an ensure-admitted
    in-progress ``RowRun``); ingest and sightings are not re-verified here.
    """
    prior_ledger_at_n_minus_1 = (
        materialize_turn == accelerated_ensure_floor(turn_context.turn.settings, materialize_turn)
    ) or (prior_persisted is not None and prior_persisted.provenance.is_final)
    turn_evidence_at_n = _is_turn_evidence_closed(
        materialize_turn=materialize_turn,
        turn_context=turn_context,
        player_id=player_id,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )
    return FleetMaterializationProvenance(
        turn_evidence_at_n=turn_evidence_at_n,
        prior_ledger_at_n_minus_1=prior_ledger_at_n_minus_1,
    )


def _is_turn_evidence_closed(
    *,
    materialize_turn: int,
    turn_context: FleetTurnContext,
    player_id: int,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
) -> bool:
    if load_turn(materialize_turn) is None:
        return False
    if not _scores_turn_evidence_closed_for_player(
        game_id=game_id,
        perspective=perspective,
        turn_number=materialize_turn,
        player_id=player_id,
        turn=turn_context.turn,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    ):
        return False
    return True


def _scores_turn_evidence_closed_for_player(
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int,
    turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
) -> bool:
    if turn_number <= 1:
        return True

    if inference_materialization is None:
        return False

    scores_services = inference_materialization.inference.scores_services
    scope = ExportScope(
        game_id=game_id,
        perspective=perspective,
        turn=turn_number,
        player_id=player_id,
    )

    def get_persisted_row(
        scoreboard_turn: int,
        row_player_id: int,
    ) -> PersistedInferenceRow | None:
        if scores_services.persistence is None:
            return None
        return scores_services.persistence.get_row(
            game_id,
            perspective,
            scoreboard_turn,
            row_player_id,
        )

    player_score = next((row for row in turn.scores if row.ownerid == player_id), None)
    snapshot = gather_scores_materialization_probe_snapshot(
        scores_services,
        scope,
        turn,
    )
    resolution_context = ScoresExportResolutionContext(
        scoreboard_turn=turn_number,
        turn=turn,
        player_id=player_id,
        load_scoreboard_turn=load_turn,
        get_persisted_row=get_persisted_row,
        player_score=player_score,
    )
    return is_scores_export_turn_evidence_closed_from_snapshot(
        snapshot,
        resolution_context=resolution_context,
    )
