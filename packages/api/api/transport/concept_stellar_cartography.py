"""HTTP contracts for game concept: Stellar Cartography sampling."""

from typing import Literal

from pydantic import BaseModel, Field

StellarCartographySampleLayerId = Literal[
    "debris-disks",
    "nebulae",
    "ion-storms",
    "star-clusters",
    "black-holes",
    "wormholes",
]


class StellarCartographySampleEntry(BaseModel):
    layer: StellarCartographySampleLayerId
    lines: list[str]


class StellarCartographySampleResponse(BaseModel):
    x: int
    y: int
    entries: list[StellarCartographySampleEntry] = Field(default_factory=list)


class StellarCartographyTurnSummaryResponse(BaseModel):
    ion_storm_count: int
    nu_ion_storms: bool
