"""HTTP contracts for global game concept: flare points."""

from enum import StrEnum

from pydantic import BaseModel, Field


class FlareMovementTypeParam(StrEnum):
    REGULAR = "regular"
    GRAVITONIC = "gravitonic"


class RelativeOffsetModel(BaseModel):
    x: int
    y: int


class FlarePointWireModel(BaseModel):
    waypoint_offset: RelativeOffsetModel
    arrival_offset: RelativeOffsetModel
    direct_aim_arrival_offset: RelativeOffsetModel


class FlarePointsListResponse(BaseModel):
    flare_points: list[FlarePointWireModel] = Field(default_factory=list)
