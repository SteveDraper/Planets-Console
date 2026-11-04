"""HTTP transport for the homeworld fleet-age refetch notice."""

from pydantic import BaseModel, ConfigDict, Field


class FleetAgeRefetchNoticeResponse(BaseModel):
    """Epoch of on-disk build-turn identity changes and the earliest changed turn."""

    model_config = ConfigDict(populate_by_name=True)

    epoch: int = Field(description="Monotonic count of build-turn identity changes for this game.")
    from_turn: int | None = Field(
        default=None,
        alias="fromTurn",
        description=(
            "Earliest turn whose build-turn identity changed after afterEpoch. "
            "Null when the epoch has not moved. 1 when the retained window no longer "
            "holds the changes."
        ),
    )
