"""Fixtures for scores/fleet export ensure-chain tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
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
from api.analytics.fleet.held_solutions import (
    FleetInferenceMaterialization,
    FleetInferenceSupport,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.turn_roster import iter_turn_players
from api.errors import NotFoundError
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.turn import turn_info_from_json, turn_info_to_json
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend

GAME_ID = 628580


@dataclass(frozen=True)
class ExportSeedContext:
    """Minimal context for ``seed_fleet_unwind_through``."""

    game_id: int
    perspective: int
    load_turn: Callable[[int], object | None]
    export_services: Mapping[str, object]


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
    ctx: ExportSeedContext | AnalyticQueryContext,
    *,
    through_turn: int,
    player_id: int | Iterable[int],
) -> None:
    """Persist terminal scores rows and fleet snapshots for turns 1..through_turn-1."""
    player_ids = (player_id,) if isinstance(player_id, int) else tuple(player_id)
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
        for row_player_id in player_ids:
            scores_services.persistence.put_row(
                ctx.game_id,
                ctx.perspective,
                turn_number,
                row_player_id,
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


def seed_storage_analytics_fixture(
    storage: StorageBackend,
    *,
    assets_dir: Path,
    host_turn: int,
    game_id: int = GAME_ID,
    perspective: int = 1,
    seed_player_ids: tuple[int, ...] | None = None,
) -> None:
    """Seed game info, turns 1..host_turn, and export prerequisites in durable storage."""
    with open(assets_dir / "game_info_sample.json") as handle:
        storage.put(f"games/{game_id}/info", json.load(handle))

    with open(assets_dir / "turn_sample.json") as handle:
        sample_turn = turn_info_from_json(json.load(handle))

    host_turn_info = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=host_turn),
        game=replace(sample_turn.game, turn=host_turn),
    )
    for turn_number, turn_info in turn_chain_through(host_turn_info).items():
        storage.put(
            f"games/{game_id}/{perspective}/turns/{turn_number}",
            turn_info_to_json(turn_info),
        )

    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    turns = TurnLoadService(storage, credentials, games)

    def load_turn(turn_number: int):
        try:
            return turns.get_turn_info(game_id, perspective, turn_number)
        except OSError, ValueError, KeyError, NotFoundError:
            return None

    inference_persistence = InferenceRowPersistenceService(storage)
    fleet_persistence = FleetSnapshotPersistenceService(storage)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    fleet_services = FleetComputeServices(
        persistence=fleet_persistence,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(scores_services=scores_services),
            load_turn=load_turn,
        ),
    )
    if seed_player_ids is None:
        ambient_turn = turns.get_turn_info(game_id, perspective, host_turn)
        seed_player_ids = tuple(player.id for player in iter_turn_players(ambient_turn))
    seed_fleet_unwind_through(
        ExportSeedContext(
            game_id=game_id,
            perspective=perspective,
            load_turn=load_turn,
            export_services={
                "scores": scores_services,
                "fleet": fleet_services,
            },
        ),
        through_turn=host_turn,
        player_id=seed_player_ids,
    )
