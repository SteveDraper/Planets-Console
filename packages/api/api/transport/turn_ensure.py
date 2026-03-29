"""Request body for POST .../turns/ensure (BFF aggregates turn + credentials)."""

from pydantic import BaseModel, Field


class TurnEnsureRequest(BaseModel):
    """Parameters to ensure turn data exists in storage for a game and perspective slot."""

    turn: int = Field(ge=1)
    perspective: int = Field(ge=1)
    username: str = Field(
        default="",
        description=(
            "Planets.nu account; required only when turn data is missing from storage "
            "and must be loaded from upstream."
        ),
    )
    password: str | None = None
