"""Turn-scoped game concept lookups (warp wells, planet resolution)."""

from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
)
from api.models.game import TurnInfo
from api.services.turn_load_service import TurnLoadService


class TurnConceptService:
    """Evaluate turn-scoped concepts against stored ``TurnInfo``."""

    def __init__(self, turns: TurnLoadService) -> None:
        self._turns = turns

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        return self._turns.get_turn_info(game_id, perspective, turn_number)

    def warp_well_coordinate_in_well(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        planet_id: int,
        map_x: float,
        map_y: float,
        well_kind: WarpWellKind,
    ) -> bool:
        planet = self._turns.get_planet_from_turn(game_id, perspective, turn_number, planet_id)
        return coordinate_in_warp_well(planet, map_x, map_y, well_kind)

    def warp_well_cells(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        planet_id: int,
        well_kind: WarpWellKind,
    ) -> list[dict[str, int]]:
        planet = self._turns.get_planet_from_turn(game_id, perspective, turn_number, planet_id)
        return [{"x": gx, "y": gy} for gx, gy in map_cell_indices_in_warp_well(planet, well_kind)]
