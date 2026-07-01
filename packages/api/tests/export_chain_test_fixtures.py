"""Fixtures for scores/fleet export ensure-chain tests."""

from __future__ import annotations

from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import (
    _GapFillCoherence,
    _materialize_fleet_snapshot_chain,
    gap_fill_coherence_scope,
)
from api.analytics.fleet.compute_services import (
    FleetComputeServices,
    build_ephemeral_fleet_compute_services,
    turn_chain_through,
)
from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

GAME_ID = 628580


def export_chain_query_context(
    sample_turn,
    *,
    persistence: InferenceRowPersistenceService | None = None,
    scheduler: InferenceRowScheduler | None = None,
    stored_turns: dict[int, object] | None = None,
    seed_fleet_prerequisites_for: int | None = None,
):
    """Scores + fleet query context with a full 1..T turn chain."""
    turns = stored_turns if stored_turns is not None else turn_chain_through(sample_turn)
    perspective_id = sample_turn.player.id

    def load_turn(turn_number: int):
        return turns.get(turn_number)

    scores_services = ScoresExportContext(persistence=persistence)
    if scheduler is not None:
        scores_services = ScoresExportContext(
            persistence=persistence,
            scheduler=scheduler,
        )

    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=GAME_ID,
        perspective=perspective_id,
        stored_turns=turns,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={
            "scores": scores_services,
            "fleet": fleet_services,
        },
    )
    if seed_fleet_prerequisites_for is not None:
        seed_fleet_unwind_through(
            ctx,
            through_turn=sample_turn.settings.turn,
            player_id=seed_fleet_prerequisites_for,
        )
    return ctx


def seed_fleet_unwind_through(
    ctx,
    *,
    through_turn: int,
    player_id: int,
) -> None:
    """Persist terminal scores rows and fleet snapshots for turns 1..through_turn-1."""
    fleet_services = ctx.export_services["fleet"]
    if not isinstance(fleet_services, FleetComputeServices):
        raise TypeError("seed_fleet_unwind_through requires FleetComputeServices on ctx")

    scores_services = ctx.export_services["scores"]
    if scores_services.persistence is None:
        raise RuntimeError("seed_fleet_unwind_through requires scores persistence")

    for turn_number in range(1, through_turn):
        turn = ctx.load_turn(turn_number)
        if turn is None:
            raise RuntimeError(f"seed_fleet_unwind_through missing stored turn {turn_number}")
        scores_services.persistence.put_row(
            ctx.game_id,
            ctx.perspective,
            turn_number,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seed",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )
        generation = fleet_services.persistence.invalidation_generation(
            ctx.game_id,
            ctx.perspective,
        )
        coherence = _GapFillCoherence(
            fleet_services.persistence,
            ctx.game_id,
            ctx.perspective,
            generation,
        )
        with gap_fill_coherence_scope(coherence):
            _materialize_fleet_snapshot_chain(
                fleet_services.persistence,
                ctx.game_id,
                ctx.perspective,
                turn,
                load_turn=ctx.load_turn,
                inference_materialization=fleet_services.inference_materialization,
                coherence=coherence,
            )
