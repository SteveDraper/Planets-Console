"""Request bodies for POST /v1/games/{game_id}/info."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from api.models.game_info_operations import GameInfoUpdateOperation


class RefreshGameInfoParams(BaseModel):
    """Parameters for operation `refresh`."""

    username: str = Field(
        default="",
        description="Non-empty required for refresh; ensure-turn may omit when data is local.",
    )
    password: str | None = None


class GameInfoUpdateRequest(BaseModel):
    operation: GameInfoUpdateOperation
    params: dict[str, Any]

    @model_validator(mode="after")
    def validate_params_for_operation(self) -> GameInfoUpdateRequest:
        match self.operation:
            case GameInfoUpdateOperation.REFRESH:
                RefreshGameInfoParams.model_validate(self.params)
            case _:
                raise ValueError(f"Unsupported operation: {self.operation!r}")
        return self
