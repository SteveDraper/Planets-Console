"""SPA shell bootstrap: config surfaced for first paint without hard-coding in the frontend."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from bff.config import get_config
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()


class ShellBootstrapResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    show_initial_game: str | None = Field(
        default=None,
        serialization_alias="showInitialGame",
        description="Stored game id to load automatically without login, or null when disabled.",
    )


@router.get("/bootstrap")
def get_shell_bootstrap(include: IncludeDiagnostics = False) -> object:
    """Return shell-oriented server config for the SPA (e.g. optional default game id)."""
    raw = get_config().show_initial_game
    if raw is None:
        show: str | None = None
    else:
        trimmed = raw.strip()
        show = trimmed if trimmed else None
    root = optional_request_root(include, "GET", "/shell/bootstrap", handler="get_shell_bootstrap")

    def work() -> ShellBootstrapResponse:
        return ShellBootstrapResponse(show_initial_game=show)

    result = with_timed_child(root, "get_shell_bootstrap", "total", work)
    return finish_response(result, root)
