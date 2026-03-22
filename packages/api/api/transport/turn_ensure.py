"""Request body for POST .../turns/ensure (BFF aggregates turn + credentials)."""

from pydantic import BaseModel, Field


class TurnEnsureRequest(BaseModel):
    """Parameters to ensure turn data exists in storage for a game and perspective slot."""

    turn: int = Field(ge=1)
    perspective: int = Field(ge=1)
    username: str = Field(min_length=1)
    password: str | None = None
