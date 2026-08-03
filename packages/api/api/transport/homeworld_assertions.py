"""HTTP transport models for homeworld locator assertions (#37)."""

from pydantic import BaseModel, Field


class HomeworldAssertionRequest(BaseModel):
    """Upsert or revoke a location or ownership homeworld assertion."""

    axis: str
    action: str
    planet_id: int | None = Field(default=None, alias="planetId")
    sector_index: int | None = Field(default=None, alias="sectorIndex")
    owner_slot: int | None = Field(default=None, alias="ownerSlot")

    model_config = {"populate_by_name": True}
