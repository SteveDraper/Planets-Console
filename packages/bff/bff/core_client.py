"""In-process facade to Core services for BFF routers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import NotFoundError, PlanetsConsoleError
from api.handlers.warp_well import coordinate_in_well, warp_well_cells
from api.models.game import GameInfo, TurnInfo
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.storage import get_storage
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams
from api.transport.sector_display import (
    sector_display_name_from_game_info,
    sector_display_name_from_stored_payload,
)
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import HTTPException

from bff.transport.game_responses import StoredTurnPerspectivesResponse

T = TypeVar("T")

_sector_title_by_stored_game_id: dict[str, str | None] = {}


class CoreClient:
    """Allowed Core surface for BFF routers: services only, no direct storage in routes."""

    def __init__(
        self,
        *,
        game_service: GameService | None = None,
        store_service: StoreService | None = None,
        planets_client_factory: Callable[[], PlanetsNuClient] | None = None,
    ) -> None:
        storage = get_storage()
        self._games = game_service or GameService(storage)
        self._store = store_service or StoreService(storage)
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

    def _resolved_sector_title_for_listed_game(self, game_id: str) -> str | None:
        cached = _sector_title_by_stored_game_id.get(game_id)
        if cached is not None or game_id in _sector_title_by_stored_game_id:
            return cached
        try:
            raw = self._store.read(f"games/{game_id}/info")
        except NotFoundError:
            _sector_title_by_stored_game_id[game_id] = None
            return None
        title = sector_display_name_from_stored_payload(raw)
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
            lambda: self._games.list_stored_turn_perspectives(game_id, turn_number)
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

    def ensure_turn(self, game_id: int, body: TurnEnsureRequest) -> TurnInfo:
        planets = self._planets_client_factory()
        params = RefreshGameInfoParams(username=body.username, password=body.password)

        def work() -> TurnInfo:
            return self._games.ensure_turn_loaded(
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
            lambda: coordinate_in_well(self._games, game_id, perspective, turn_number, body)
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
                self._games,
                game_id,
                perspective,
                turn_number,
                planet_id,
                well_type,
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
            lambda: self._games.get_turn_analytics(
                game_id,
                perspective,
                turn_number,
                analytic_id,
                diagnostics=diagnostics,
                **kwargs,
            )
        )


def get_core_client() -> CoreClient:
    return CoreClient()


def clear_sector_title_cache() -> None:
    _sector_title_by_stored_game_id.clear()
