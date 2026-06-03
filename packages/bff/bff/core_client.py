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
from api.services.stack import build_service_stack
from api.services.store_service import StoreService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage import get_storage
from api.storage.base import StorageBackend
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
from api.transport.sector_display import (
    sector_display_name_from_game_info,
    sector_display_name_from_stored_payload,
)
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import HTTPException

from bff.transport.game_responses import (
    LoadAllTurnsStatusResponse as BffLoadAllTurnsStatusResponse,
)
from bff.transport.game_responses import (
    StoredTurnPerspectivesResponse,
)

T = TypeVar("T")

_sector_title_by_stored_game_id: dict[str, str | None] = {}


class CoreClient:
    """Allowed Core surface for BFF routers: services only, no direct storage in routes."""

    def __init__(
        self,
        *,
        game_service: GameService | None = None,
        turn_load_service: TurnLoadService | None = None,
        load_all_turns_service: LoadAllTurnsService | None = None,
        turn_concept_service: TurnConceptService | None = None,
        turn_analytic_service: TurnAnalyticService | None = None,
        store_service: StoreService | None = None,
        planets_client_factory: Callable[[], PlanetsNuClient] | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        backend = storage or get_storage()
        games, turns, load_all, concepts, analytics = build_service_stack(backend)
        self._games = game_service or games
        self._turns = turn_load_service or turns
        self._load_all = load_all_turns_service or load_all
        self._concepts = turn_concept_service or concepts
        self._analytics = turn_analytic_service or analytics
        self._store = store_service or StoreService(backend)
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
        def work() -> dict[str, list[dict[str, str]]]:
            try:
                shallow = self._store.read_shallow("games")
            except NotFoundError:
                return {"games": []}
            children = shallow.get("children") or []
            games: list[dict[str, str]] = []
            for child in children:
                game_id = str(child)
                entry: dict[str, str] = {"id": game_id}
                sector = self._resolved_sector_title_for_listed_game(game_id)
                if sector is not None:
                    entry["sectorName"] = sector
                games.append(entry)
            return {"games": games}

        return self._invoke(work)

    def _resolved_sector_title_for_listed_game(self, game_id: str) -> str | None:
        cached = _sector_title_by_stored_game_id.get(game_id)
        if cached is not None or game_id in _sector_title_by_stored_game_id:
            return cached

        def read_title() -> str | None:
            try:
                raw = self._store.read(f"games/{game_id}/info")
            except NotFoundError:
                return None
            return sector_display_name_from_stored_payload(raw)

        title = self._invoke(read_title)
        _sector_title_by_stored_game_id[game_id] = title
        return title

    def remember_sector_title_for_game(self, game_id: int, info: GameInfo) -> None:
        title = sector_display_name_from_game_info(info)
        _sector_title_by_stored_game_id[str(game_id)] = title

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

        updated = self._invoke(work)
        self.remember_sector_title_for_game(game_id, updated)
        return updated

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


def get_core_client() -> CoreClient:
    return CoreClient()


def clear_sector_title_cache() -> None:
    _sector_title_by_stored_game_id.clear()
