"""Turn analytic dispatch via the Core analytics registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, NamedTuple

from api.analytics import TurnAnalyticsOptions
from api.analytics.compute_context import make_analytic_compute_context
from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.fleet import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.homeworld_locator.compute_services import HomeworldLocatorComputeServices
from api.analytics.homeworld_locator.constants import ANALYTIC_ID as HOMEWORLD_ANALYTIC_ID
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.registry import dispatch_turn_analytic
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.batch_compute import ensure_table_map_compute
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import LoginCredentialsRequiredError, NotFoundError, UpstreamPlanetsError
from api.models.game import TurnInfo
from api.planets_nu import PlanetsNuClient
from api.services.homeworld_assertion_service import HomeworldAssertionService
from api.services.inference_hull_catalog_service import InferenceHullCatalogService
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.connections_options import FlareConnectionMode
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.homeworld_assertions import (
    HomeworldAssertionAction,
    HomeworldAssertionAxis,
)

if TYPE_CHECKING:
    from api.analytics.exports.catalog import AnalyticExportCatalog
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler


class _QueryComputeContextIngredients(NamedTuple):
    """Shared turn, load_turn, export_services, and fleet ensure_turn for query/compute context."""

    turn: TurnInfo
    load_turn: Callable[[int], TurnInfo | None]
    export_services: dict[str, object]
    ensure_turn: Callable[[int], TurnInfo | None] | None


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
        homeworld_persistence: HomeworldLocatorPersistenceService | None = None,
        planets_client_factory: Callable[[], PlanetsNuClient] | None = None,
    ) -> None:
        self._turns = turns
        self._planets_client_factory = planets_client_factory or PlanetsNuClient.from_config
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
        if homeworld_persistence is not None:
            self._homeworld_persistence = homeworld_persistence
        else:
            self._homeworld_persistence = HomeworldLocatorPersistenceService(storage)
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

    def _query_compute_context_ingredients(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        username: str = "",
    ) -> _QueryComputeContextIngredients:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        load_turn = self._load_scoreboard_turn(game_id, perspective)
        export_services = self._turn_export_services(
            game_id,
            perspective,
            username=username,
        )
        fleet_services = export_services[FLEET_ANALYTIC_ID]
        ensure_turn = (
            fleet_services.ensure_turn if isinstance(fleet_services, FleetComputeServices) else None
        )
        return _QueryComputeContextIngredients(
            turn=turn,
            load_turn=load_turn,
            export_services=export_services,
            ensure_turn=ensure_turn,
        )

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
        username: str = "",
    ) -> dict:
        """Dispatch a registered turn analytic.

        Analytics with a compute profile and ``route_table_map=True`` are
        ensured through the orchestrator first (batch fan-out, cache-hit
        inline short-circuit). ``compute()`` then shapes the table/map wire.

        ``username`` is an optional turn-load credential for analytics that may
        auto-ensure missing turns (stored account API key lookup). Empty skips
        turn-load ensure.
        """
        ingredients = self._query_compute_context_ingredients(
            game_id,
            perspective,
            turn_number,
            username=username,
        )
        options = TurnAnalyticsOptions(
            connection_warp_speed=connection_warp_speed,
            connection_gravitonic_movement=connection_gravitonic_movement,
            connection_flare_mode=connection_flare_mode,
            connection_flare_depth=connection_flare_depth,
            connection_include_illustrative_routes=connection_include_illustrative_routes,
            diagnostics=diagnostics,
        )
        compute_ctx = make_analytic_compute_context(
            ingredients.turn,
            options,
            load_turn=ingredients.load_turn,
            export_services=ingredients.export_services,
            game_id=game_id,
            perspective=perspective,
            ensure_turn=ingredients.ensure_turn,
        )
        ensure_table_map_compute(compute_ctx.exports, analytic_id, ingredients.turn)
        return dispatch_turn_analytic(analytic_id, compute_ctx)

    def export_query_context(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        username: str = "",
        export_registry: Mapping[str, AnalyticExportCatalog] | None = None,
    ) -> AnalyticQueryContext:
        """Build an analytic query context for in-process hatch-read / probe / admit.

        Does not dispatch table/map compute. ``username`` enables login-backed
        dependency-turn fill on live ensure; hatch-read does not auto-load turns.
        """
        ingredients = self._query_compute_context_ingredients(
            game_id,
            perspective,
            turn_number,
            username=username,
        )
        return make_analytic_query_context(
            ingredients.turn,
            TurnAnalyticsOptions(),
            game_id=game_id,
            perspective=perspective,
            load_turn=ingredients.load_turn,
            export_registry=export_registry,
            export_services=ingredients.export_services,
            ensure_turn=ingredients.ensure_turn,
        )

    def _turn_export_services(
        self,
        game_id: int,
        perspective: int,
        *,
        username: str = "",
    ) -> dict[str, object]:
        scores_services = self._scores_export_context(game_id, perspective)
        ensure_turn = self._ensure_turn_loader(game_id, perspective, username)
        return {
            SCORES_ANALYTIC_ID: scores_services,
            FLEET_ANALYTIC_ID: self._fleet_compute_services(
                game_id,
                perspective,
                scores_services=scores_services,
                ensure_turn=ensure_turn,
            ),
            HOMEWORLD_ANALYTIC_ID: self._homeworld_compute_services(
                game_id,
                perspective,
                ensure_turn=ensure_turn,
            ),
        }

    def _ensure_turn_loader(
        self,
        game_id: int,
        perspective: int,
        username: str,
    ) -> Callable[[int], TurnInfo | None] | None:
        """Build a turn-ensure hook when a turn-load username credential is present."""
        trimmed = username.strip()
        if not trimmed:
            return None

        def ensure_turn(turn_number: int) -> TurnInfo | None:
            """Load missing turn via stored account API key; None when credentials/upstream fail."""
            try:
                return self._turns.ensure_turn_loaded(
                    game_id,
                    perspective,
                    turn_number,
                    RefreshGameInfoParams(username=trimmed),
                    self._planets_client_factory(),
                )
            except LoginCredentialsRequiredError, UpstreamPlanetsError, NotFoundError, OSError:
                return None

        return ensure_turn

    def _homeworld_compute_services(
        self,
        game_id: int,
        perspective: int,
        *,
        ensure_turn: Callable[[int], TurnInfo | None] | None = None,
    ) -> HomeworldLocatorComputeServices:
        load_turn = self._load_scoreboard_turn(game_id, perspective)

        def list_stored_turns() -> list[int]:
            return self._turns.list_stored_turn_numbers(game_id, perspective)

        return HomeworldLocatorComputeServices(
            persistence=self._homeworld_persistence,
            game_id=game_id,
            perspective=perspective,
            load_turn=load_turn,
            list_stored_turns=list_stored_turns,
            ensure_turn=ensure_turn,
        )

    def _fleet_compute_services(
        self,
        game_id: int,
        perspective: int,
        *,
        scores_services: ScoresExportContext,
        ensure_turn: Callable[[int], TurnInfo | None] | None = None,
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
            ensure_turn=ensure_turn,
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
            prior_fleet_max_tech_by_axis=fleet_resolution.prior_fleet_max_tech_for_admission(),
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
            player_ids=player_ids,
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
            export_services=export_services,
            persistence=self._inference_persistence,
            scheduler=self._inference_scheduler_instance(),
        )

    def iter_fleet_table_stream(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
        username: str = "",
    ):
        from api.analytics.fleet import iter_fleet_table_stream
        from api.analytics.fleet.fleet_table_stream_scheduler import (
            get_fleet_table_stream_scheduler,
        )

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        export_services = self._turn_export_services(
            game_id,
            perspective,
            username=username,
        )
        fleet_services = export_services[FLEET_ANALYTIC_ID]
        return iter_fleet_table_stream(
            turn,
            player_ids,
            game_id=game_id,
            perspective=perspective,
            fleet_services=fleet_services,
            persistence=self._fleet_persistence,
            scheduler=get_fleet_table_stream_scheduler(),
        )

    def _inference_scheduler_instance(self) -> InferenceRowScheduler:
        if self._inference_scheduler is not None:
            return self._inference_scheduler
        from api.analytics.military_score_inference.inference_scheduler import (
            get_inference_row_scheduler,
        )

        return get_inference_row_scheduler()

    def shutdown_background_workers(self) -> None:
        if self._inference_scheduler is not None:
            self._inference_scheduler.shutdown()

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

    def _homeworld_assertion_service(
        self,
        game_id: int,
        perspective: int,
    ):
        load_turn = self._load_scoreboard_turn(game_id, perspective)

        def rematerialize(turn_number: int) -> dict:
            return self.get_turn_analytics(
                game_id,
                perspective,
                turn_number,
                HOMEWORLD_ANALYTIC_ID,
            )

        return HomeworldAssertionService(
            persistence=self._homeworld_persistence,
            load_turn=load_turn,
            game_id=game_id,
            perspective=perspective,
            rematerialize=rematerialize,
        )

    def apply_homeworld_assertion(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        axis: HomeworldAssertionAxis,
        action: HomeworldAssertionAction,
        planet_id: int | None = None,
        sector_index: int | None = None,
        owner_slot: int | None = None,
    ) -> dict:
        return self._homeworld_assertion_service(game_id, perspective).apply_assertion(
            axis=axis,
            action=action,
            turn_number=turn_number,
            planet_id=planet_id,
            sector_index=sector_index,
            owner_slot=owner_slot,
        )

    def refresh_homeworld_locator(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict:
        return self._homeworld_assertion_service(game_id, perspective).refresh(
            turn_number=turn_number,
        )
