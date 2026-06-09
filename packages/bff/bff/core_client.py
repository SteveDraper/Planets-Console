"""In-process facade to Core services for BFF routers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeVar

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import NotFoundError, PlanetsConsoleError
from api.handlers.stellar_cartography import (
    sample_at as stellar_cartography_sample_at,
)
from api.handlers.stellar_cartography import (
    turn_summary as stellar_cartography_turn_summary_handler,
)
from api.handlers.warp_well import coordinate_in_well, warp_well_cells
from api.models.game import GameInfo, TurnInfo
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.stack import build_default_service_stack
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.transport.concept_stellar_cartography import (
    StellarCartographySampleResponse,
    StellarCartographyTurnSummaryResponse,
)
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams
from api.transport.load_all_turns import LoadAllStreamItem
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import HTTPException

from bff.transport.game_responses import (
    LoadAllTurnsStatusResponse as BffLoadAllTurnsStatusResponse,
)
from bff.transport.game_responses import (
    StoredTurnPerspectivesResponse,
)

T = TypeVar("T")


class CoreClient:
    """Allowed Core surface for BFF routers: services only, no direct storage in routes."""

    def __init__(
        self,
        *,
        game_service: GameService,
        turn_load_service: TurnLoadService,
        load_all_turns_service: LoadAllTurnsService,
        turn_concept_service: TurnConceptService,
        turn_analytic_service: TurnAnalyticService,
        planets_client_factory: Callable[[], PlanetsNuClient] | None = None,
    ) -> None:
        self._games = game_service
        self._turns = turn_load_service
        self._load_all = load_all_turns_service
        self._concepts = turn_concept_service
        self._analytics = turn_analytic_service
        self._planets_client_factory = planets_client_factory or PlanetsNuClient.from_config

    def _invoke(self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except PlanetsConsoleError as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_error", 500),
                detail=str(exc),
            ) from exc

    def list_stored_games(self) -> dict[str, list[dict[str, str]]]:
        return self._invoke(self._games.list_stored_games)

    def list_stored_turn_perspectives(
        self,
        game_id: int,
        turn_number: int,
    ) -> StoredTurnPerspectivesResponse:
        perspectives = self._invoke(
            lambda: self._turns.list_stored_turn_perspectives(game_id, turn_number)
        )
        return StoredTurnPerspectivesResponse(perspectives=perspectives)

    def get_stored_game_info(self, game_id: int) -> GameInfo:
        return self._invoke(lambda: self._games.get_game_info(game_id))

    def refresh_game_info(self, game_id: int, body: GameInfoUpdateRequest) -> GameInfo:
        planets = self._planets_client_factory()

        def work() -> GameInfo:
            return self._games.update_game_info(game_id, body, planets)

        return self._invoke(work)

    def load_all_turns_status(self, game_id: int, username: str) -> BffLoadAllTurnsStatusResponse:
        def work() -> BffLoadAllTurnsStatusResponse:
            core_status = self._load_all.load_all_turns_status_for_user(game_id, username)
            return BffLoadAllTurnsStatusResponse.model_validate(core_status.model_dump())

        return self._invoke(work)

    def iter_load_all_turns(
        self, game_id: int, username: str, password: str | None
    ) -> Iterator[LoadAllStreamItem]:
        params = RefreshGameInfoParams(username=username, password=password)
        planets = self._planets_client_factory()
        yield from self._load_all.iter_load_all_turns(game_id, params, planets)

    def ensure_turn(self, game_id: int, body: TurnEnsureRequest) -> TurnInfo:
        params = RefreshGameInfoParams(username=body.username, password=body.password)

        def work() -> TurnInfo:
            try:
                return self._turns.get_turn_info(game_id, body.perspective, body.turn)
            except NotFoundError:
                planets = self._planets_client_factory()
                return self._turns.ensure_turn_loaded(
                    game_id,
                    body.perspective,
                    body.turn,
                    params,
                    planets,
                )

        return self._invoke(work)

    def warp_well_coordinate_in_well(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        body: CoordinateInWarpWellRequest,
    ) -> CoordinateInWarpWellResponse:
        return self._invoke(
            lambda: coordinate_in_well(self._concepts, game_id, perspective, turn_number, body)
        )

    def warp_well_cells(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        planet_id: int,
        well_type: WarpWellTypeParam,
    ) -> WarpWellCellsResponse:
        return self._invoke(
            lambda: warp_well_cells(
                self._concepts,
                game_id,
                perspective,
                turn_number,
                planet_id,
                well_type,
            )
        )

    def stellar_cartography_sample(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        x: int,
        y: int,
    ) -> StellarCartographySampleResponse:
        return self._invoke(
            lambda: stellar_cartography_sample_at(
                self._concepts,
                game_id,
                perspective,
                turn_number,
                x,
                y,
            )
        )

    def stellar_cartography_turn_summary(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> StellarCartographyTurnSummaryResponse:
        return self._invoke(
            lambda: stellar_cartography_turn_summary_handler(
                self._concepts,
                game_id,
                perspective,
                turn_number,
            )
        )

    def get_turn_analytics(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        analytic_id: str,
        *,
        diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
        **kwargs: object,
    ) -> dict:
        return self._invoke(
            lambda: self._analytics.get_turn_analytics(
                game_id,
                perspective,
                turn_number,
                analytic_id,
                diagnostics=diagnostics,
                **kwargs,
            )
        )

    def get_scores_row_inference(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        *,
        diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    ) -> dict[str, object]:
        _ = diagnostics
        return self._invoke(
            lambda: self._analytics.get_scores_row_inference(
                game_id,
                perspective,
                turn_number,
                player_id,
            )
        )

    def iter_scores_table_inference_stream(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        yield from self._analytics.iter_scores_table_inference_stream(
            game_id,
            perspective,
            turn_number,
            player_ids,
        )

    def get_inference_global_pause_status(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        return self._invoke(
            lambda: self._analytics.get_inference_global_pause_status(
                game_id,
                perspective,
                turn_number,
            )
        )

    def pause_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        return self._invoke(
            lambda: self._analytics.pause_inference_globally(
                game_id,
                perspective,
                turn_number,
            )
        )

    def resume_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        return self._invoke(
            lambda: self._analytics.resume_inference_globally(
                game_id,
                perspective,
                turn_number,
            )
        )


_core_client_singleton: CoreClient | None = None


def clear_core_client_cache() -> None:
    """Drop the cached client (tests after ``clear_backend_cache`` / config change)."""
    global _core_client_singleton
    _core_client_singleton = None


def _build_core_client() -> CoreClient:
    games, turns, load_all, concepts, analytics = build_default_service_stack()
    return CoreClient(
        game_service=games,
        turn_load_service=turns,
        load_all_turns_service=load_all,
        turn_concept_service=concepts,
        turn_analytic_service=analytics,
    )


def get_core_client() -> CoreClient:
    """Process-singleton in-process Core facade (one service stack per storage backend)."""
    global _core_client_singleton
    if _core_client_singleton is None:
        _core_client_singleton = _build_core_client()
    return _core_client_singleton
