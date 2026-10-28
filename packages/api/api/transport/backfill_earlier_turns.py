"""HTTP body for reading and writing Backfill earlier turns."""

from pydantic import BaseModel, Field

from api.serialization.backfill_earlier_turns import BACKFILL_EARLIER_TURNS_FIELD


class BackfillEarlierTurnsBody(BaseModel):
    """The only field on a Backfill earlier turns read or write."""

    model_config = {"populate_by_name": True, "extra": "forbid"}

    backfill_earlier_turns: bool = Field(
        alias=BACKFILL_EARLIER_TURNS_FIELD,
        strict=True,
        title="Backfill earlier turns",
    )
