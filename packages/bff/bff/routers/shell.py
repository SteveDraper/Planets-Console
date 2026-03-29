"""SPA shell bootstrap: config surfaced for first paint without hard-coding in the frontend."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from bff.config import get_config

router = APIRouter()


class ShellBootstrapResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    show_initial_game: str | None = Field(
        default=None,
        serialization_alias="showInitialGame",
        description="Stored game id to load automatically without login, or null when disabled.",
    )


@router.get("/bootstrap")
def get_shell_bootstrap() -> ShellBootstrapResponse:
    """Return shell-oriented server config for the SPA (e.g. optional default game id)."""
    raw = get_config().show_initial_game
    if raw is None:
        return ShellBootstrapResponse(show_initial_game=None)
    trimmed = raw.strip()
    return ShellBootstrapResponse(show_initial_game=trimmed if trimmed else None)
