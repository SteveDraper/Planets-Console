"""Full shell-context binding for turn-scoped MCP tools."""

from __future__ import annotations

from typing import Literal, TypedDict, TypeGuard

from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.ship import Ship
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService

from mcp_adapter.eligibility import require_eligible_perspective


class NeedsEnsureResult(TypedDict):
    status: Literal["unavailable"]
    reason: Literal["needs_ensure"]


NEEDS_ENSURE_RESULT: NeedsEnsureResult = {
    "status": "unavailable",
    "reason": "needs_ensure",
}


def is_needs_ensure(result: TurnInfo | NeedsEnsureResult) -> TypeGuard[NeedsEnsureResult]:
    """True when load_stored_turn returned the missing-turn envelope."""
    return isinstance(result, dict)


def load_stored_turn(
    game_service: GameService,
    turn_load_service: TurnLoadService,
    *,
    login_identity: str,
    game_id: int,
    turn: int,
    perspective: int,
) -> TurnInfo | NeedsEnsureResult:
    """Return stored TurnInfo for an eligible perspective, or needs_ensure.

    Does not auto-ensure. Ineligible perspective raises viewpoint-eligibility refuse.
    """
    require_eligible_perspective(
        game_service,
        login_identity=login_identity,
        game_id=game_id,
        perspective=perspective,
    )
    if not turn_load_service.is_turn_stored(game_id, perspective, turn):
        return NEEDS_ENSURE_RESULT
    return turn_load_service.get_turn_info(game_id, perspective, turn)


def planet_on_turn(turn: TurnInfo, planet_id: int) -> Planet:
    """Return the named planet in this TurnInfo, or not-found."""
    for planet in turn.planets:
        if planet.id == planet_id:
            return planet
    raise NotFoundError(f"No planet id {planet_id} in this perspective's stored TurnInfo.")


def ship_on_turn(turn: TurnInfo, ship_id: int) -> Ship:
    """Return the named ship in this TurnInfo, or not-found."""
    for ship in turn.ships:
        if ship.id == ship_id:
            return ship
    raise NotFoundError(f"No ship id {ship_id} in this perspective's stored TurnInfo.")
