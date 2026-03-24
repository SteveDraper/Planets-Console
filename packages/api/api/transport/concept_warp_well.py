"""HTTP contracts for game concept: warp wells (turn-scoped)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class WarpWellTypeParam(StrEnum):
    NORMAL = "normal"
    HYPERJUMP = "hyperjump"


class CoordinateInWarpWellRequest(BaseModel):
    planet_id: int = Field(ge=1)
    map_x: float
    map_y: float
    well_type: WarpWellTypeParam


class CoordinateInWarpWellResponse(BaseModel):
    inside: bool


class MapCellModel(BaseModel):
    x: int
    y: int


class WarpWellCellsResponse(BaseModel):
    cells: list[MapCellModel]
