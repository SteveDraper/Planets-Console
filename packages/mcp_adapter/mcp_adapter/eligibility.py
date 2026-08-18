"""Viewpoint eligibility checks for MCP shell-context tools."""

from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.viewpoint_eligibility import ViewpointEligibilityService

from mcp_adapter.errors import ViewpointEligibilityRefusedError


def eligible_perspectives_for_login(
    game_service: GameService,
    *,
    login_identity: str,
    game_id: int,
) -> frozenset[int]:
    """Allowed perspective slots for this login, from stored GameInfo."""
    info = game_service.get_game_info(game_id)
    return ViewpointEligibilityService.eligible_perspectives(info, login_identity)


def require_eligible_perspective(
    game_service: GameService,
    *,
    login_identity: str,
    game_id: int,
    perspective: int,
) -> GameInfo:
    """Return stored GameInfo, or refuse when the named slot is not allowed."""
    info = game_service.get_game_info(game_id)
    allowed = ViewpointEligibilityService.eligible_perspectives(info, login_identity)
    if perspective not in allowed:
        raise ViewpointEligibilityRefusedError(
            game_id=game_id,
            perspective=perspective,
            login_identity=login_identity,
        )
    return info
