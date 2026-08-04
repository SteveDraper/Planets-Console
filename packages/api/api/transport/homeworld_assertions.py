"""HTTP transport models for homeworld locator assertions (#37)."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, Field

HomeworldAssertionAxis: TypeAlias = Literal["location", "ownership"]
HomeworldAssertionAction: TypeAlias = Literal["upsert", "revoke"]


class HomeworldAssertionRequest(BaseModel):
    """Upsert or revoke a location or ownership homeworld assertion."""

    axis: HomeworldAssertionAxis
    action: HomeworldAssertionAction
    planet_id: int | None = Field(default=None, alias="planetId")
    sector_index: int | None = Field(default=None, alias="sectorIndex")
    owner_slot: int | None = Field(default=None, alias="ownerSlot")

    model_config = {"populate_by_name": True}
