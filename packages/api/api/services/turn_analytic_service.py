"""Turn analytic dispatch via the Core analytics registry."""

from collections.abc import Callable

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.fleet import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.services.inference_hull_catalog_service import InferenceHullCatalogService
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.connections_options import FlareConnectionMode


class TurnAnalyticService:
    """Compute registered turn analytics for a game, perspective, and turn."""

    def __init__(
        self,
        turns: TurnLoadService,
        hull_catalog_masks: InferenceHullCatalogService | None = None,
        *,
        storage: StorageBackend | None = None,
        inference_persistence: InferenceRowPersistenceService | None = None,
        inference_invalidation: InferenceInvalidationService | None = None,
        inference_scheduler: InferenceRowScheduler | None = None,
        fleet_persistence: FleetSnapshotPersistenceService | None = None,
    ) -> None:
        self._turns = turns
        if storage is None:
            from api.storage import get_storage

            storage = get_storage()
        if hull_catalog_masks is not None:
            self._hull_catalog_masks = hull_catalog_masks
        else:
            self._hull_catalog_masks = InferenceHullCatalogService(storage, turns)
        if inference_persistence is not None:
            self._inference_persistence = inference_persistence
        else:
            self._inference_persistence = InferenceRowPersistenceService(storage)
        if fleet_persistence is not None:
            self._fleet_persistence = fleet_persistence
        else:
            self._fleet_persistence = FleetSnapshotPersistenceService(storage)
        if inference_invalidation is not None:
            self._inference_invalidation = inference_invalidation
        else:
            self._inference_invalidation = InferenceInvalidationService(
                self._inference_persistence,
                fleet_persistence=self._fleet_persistence,
            )
            self._inference_invalidation.wire_fleet_invalidation_to_persistence()
            self._inference_invalidation.wire_scores_invalidation_to_fleet_persistence()
        self._inference_scheduler = inference_scheduler

    def _load_scoreboard_turn(
        self,
        game_id: int,
        perspective: int,
    ) -> Callable[[int], TurnInfo | None]:
        def load_scoreboard_turn(stored_turn_number: int) -> TurnInfo | None:
            try:
                return self._turns.get_turn_info(
                    game_id,
                    perspective,
                    stored_turn_number,
                )
            except OSError, ValueError, KeyError, NotFoundError:
                return None

        return load_scoreboard_turn

    def get_turn_analytics(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        analytic_id: str,
        *,
        connection_warp_speed: int | None = None,
        connection_gravitonic_movement: bool = False,
        connection_flare_mode: FlareConnectionMode | str = FlareConnectionMode.OFF,
        connection_flare_depth: int = 1,
        connection_include_illustrative_routes: bool = False,
        diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    ) -> dict:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        return get_turn_analytic(
            analytic_id,
            turn,
            TurnAnalyticsOptions(
                connection_warp_speed=connection_warp_speed,
                connection_gravitonic_movement=connection_gravitonic_movement,
                connection_flare_mode=connection_flare_mode,
                connection_flare_depth=connection_flare_depth,
                connection_include_illustrative_routes=connection_include_illustrative_routes,
                diagnostics=diagnostics,
            ),
            load_turn=self._load_scoreboard_turn(game_id, perspective),
            export_services=self._turn_export_services(game_id, perspective),
        )

    def _turn_export_services(
        self,
        game_id: int,
        perspective: int,
    ) -> dict[str, object]:
        scores_services = self._scores_export_context(game_id, perspective)
        return {
            SCORES_ANALYTIC_ID: scores_services,
            FLEET_ANALYTIC_ID: self._fleet_compute_services(
                game_id,
                perspective,
                scores_services=scores_services,
            ),
        }

    def _fleet_compute_services(
        self,
        game_id: int,
        perspective: int,
        *,
        scores_services: ScoresExportContext,
    ) -> FleetComputeServices:
        load_turn = self._load_scoreboard_turn(game_id, perspective)
        return FleetComputeServices(
            persistence=self._fleet_persistence,
            game_id=game_id,
            perspective=perspective,
            load_turn=load_turn,
            inference_materialization=FleetInferenceMaterialization(
                inference=FleetInferenceSupport(scores_services=scores_services),
                load_turn=load_turn,
            ),
        )

    def _scores_export_context(
        self,
        game_id: int,
        perspective: int,
    ) -> ScoresExportContext:
        def resolve_hull_catalog_mask(turn: TurnInfo, player_id: int):
            return self._hull_catalog_masks.resolve_mask_for_player_on_turn(
                turn,
                game_id,
                player_id,
            )

        return ScoresExportContext(
            persistence=self._inference_persistence,
            scheduler=self._inference_scheduler_instance(),
            resolve_hull_catalog_mask=resolve_hull_catalog_mask,
        )

    def get_scores_row_inference(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
            resolve_prior_turn_fleet_torp_overlay,
        )
        from api.analytics.scores import get_scores_row_inference

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        resolved_mask = self._hull_catalog_masks.resolve_mask_for_player(
            game_id,
            perspective,
            turn_number,
            player_id,
        )
        load_scoreboard_turn = self._load_scoreboard_turn(game_id, perspective)
        export_services = self._turn_export_services(game_id, perspective)
        fleet_resolution = resolve_prior_turn_fleet_torp_overlay(
            turn=turn,
            player_id=player_id,
            load_turn=load_scoreboard_turn,
            export_services=export_services,
        )
        return get_scores_row_inference(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
            resolved_mask=resolved_mask,
            fleet_torp_overlay=fleet_resolution.overlay,
            fleet_torp_input_status=fleet_resolution.input_status,
        )

    def iter_scores_table_inference_stream(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
            PriorTurnFleetTorpResolution,
            resolve_prior_turn_fleet_torp_overlay,
            schedule_background_prior_turn_fleet_warm,
        )
        from api.analytics.scores import iter_scores_table_inference_stream

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)

        def resolve_mask_for_player(player_id: int):
            return self._hull_catalog_masks.resolve_mask_for_player_on_turn(
                turn,
                game_id,
                player_id,
            )

        export_services = self._turn_export_services(game_id, perspective)
        load_turn = self._load_scoreboard_turn(game_id, perspective)

        schedule_background_prior_turn_fleet_warm(
            turn=turn,
            load_turn=load_turn,
            export_services=export_services,
        )

        def resolve_fleet_torp_resolution_for_player(
            player_id: int,
        ) -> PriorTurnFleetTorpResolution:
            return resolve_prior_turn_fleet_torp_overlay(
                turn=turn,
                player_id=player_id,
                load_turn=load_turn,
                export_services=export_services,
                ensure=False,
            )

        def reload_host_turn() -> TurnInfo:
            return self._turns.get_turn_info(game_id, perspective, turn_number)

        return iter_scores_table_inference_stream(
            turn,
            player_ids,
            game_id=game_id,
            perspective=perspective,
            load_scoreboard_turn=load_turn,
            reload_host_turn=reload_host_turn,
            resolve_mask_for_player=resolve_mask_for_player,
            resolve_fleet_torp_resolution_for_player=resolve_fleet_torp_resolution_for_player,
            persistence=self._inference_persistence,
            scheduler=self._inference_scheduler_instance(),
        )

    def _inference_scheduler_instance(self) -> InferenceRowScheduler:
        if self._inference_scheduler is not None:
            return self._inference_scheduler
        from api.analytics.military_score_inference.inference_scheduler import (
            get_inference_row_scheduler,
        )

        return get_inference_row_scheduler()

    def _inference_scheduler_scope(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ):
        from api.analytics.military_score_inference.inference_stream_scope import (
            InferenceStreamScope,
        )

        scope = InferenceStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
        )
        return scope, self._inference_scheduler_instance()

    def get_inference_global_pause_status(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        scope, scheduler = self._inference_scheduler_scope(
            game_id,
            perspective,
            turn_number,
        )
        return scheduler.global_pause_status(scope)

    def pause_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        scope, scheduler = self._inference_scheduler_scope(
            game_id,
            perspective,
            turn_number,
        )
        return scheduler.pause_globally(scope)

    def resume_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        scope, scheduler = self._inference_scheduler_scope(
            game_id,
            perspective,
            turn_number,
        )
        return scheduler.resume_globally(scope)

    def get_inference_hull_catalog_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        return self._hull_catalog_masks.hull_catalog_mask_payload(
            game_id,
            perspective,
            turn_number,
            player_id,
        )

    def put_inference_hull_catalog_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        enabled_hull_ids: list[int],
    ) -> dict[str, object]:
        payload = self._hull_catalog_masks.put_user_mask(
            game_id,
            perspective,
            turn_number,
            player_id,
            enabled_hull_ids,
        )
        self._inference_invalidation.on_hull_mask_changed(
            game_id,
            perspective,
            turn_number,
            player_id,
        )
        return payload

    def reset_inference_hull_catalog_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        payload = self._hull_catalog_masks.reset_user_mask(
            game_id,
            perspective,
            turn_number,
            player_id,
        )
        self._inference_invalidation.on_hull_mask_changed(
            game_id,
            perspective,
            turn_number,
            player_id,
        )
        return payload

    def recompute_scores_inference(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        self._inference_invalidation.recompute_host_turn(
            game_id,
            perspective,
            turn_number,
        )
        scope, scheduler = self._inference_scheduler_scope(
            game_id,
            perspective,
            turn_number,
        )
        return scheduler.global_pause_status(scope)
