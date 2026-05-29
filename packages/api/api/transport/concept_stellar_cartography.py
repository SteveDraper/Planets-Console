"""HTTP contracts for game concept: Stellar Cartography sampling."""

from pydantic import BaseModel, Field


class StellarCartographySampleEntry(BaseModel):
    layer: str
    lines: list[str]


class StellarCartographySampleResponse(BaseModel):
    x: int
    y: int
    entries: list[StellarCartographySampleEntry] = Field(default_factory=list)


class StellarCartographyTurnSummaryResponse(BaseModel):
    ion_storm_count: int
    nu_ion_storms: bool
