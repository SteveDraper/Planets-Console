"""Full shell-context binding for turn-scoped MCP tools."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict, TypeGuard, TypeVar

from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.player import Player
from api.models.ship import Ship
from api.models.space import IonStorm, Minefield, Wormhole
from api.models.starbase import Starbase
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

SHELL_CONTEXT_PROPERTIES = frozenset({"game_id", "turn", "perspective"})


class _HasId(Protocol):
    id: int


_Entity = TypeVar("_Entity", bound=_HasId)


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


def _named_entity(entities: list[_Entity], entity_id: int, label: str) -> _Entity:
    for entity in entities:
        if entity.id == entity_id:
            return entity
    raise NotFoundError(f"No {label} id {entity_id} in this perspective's stored TurnInfo.")


def planet_on_turn(turn: TurnInfo, planet_id: int) -> Planet:
    """Return the named planet in this TurnInfo, or not-found."""
    return _named_entity(turn.planets, planet_id, "planet")


def ship_on_turn(turn: TurnInfo, ship_id: int) -> Ship:
    """Return the named ship in this TurnInfo, or not-found."""
    return _named_entity(turn.ships, ship_id, "ship")


def minefield_on_turn(turn: TurnInfo, minefield_id: int) -> Minefield:
    """Return the named minefield in this TurnInfo, or not-found."""
    return _named_entity(turn.minefields, minefield_id, "minefield")


def ion_storm_on_turn(turn: TurnInfo, ion_storm_id: int) -> IonStorm:
    """Return the named ion storm in this TurnInfo, or not-found."""
    return _named_entity(turn.ionstorms, ion_storm_id, "ion storm")


def wormhole_on_turn(turn: TurnInfo, wormhole_id: int) -> Wormhole:
    """Return the named wormhole in this TurnInfo, or not-found."""
    return _named_entity(turn.wormholes, wormhole_id, "wormhole")


def player_on_turn(turn: TurnInfo, player_id: int) -> Player:
    """Return the named player in this TurnInfo, or not-found.

    ``player_id`` is ``Player.id``, not the perspective slot.
    """
    return _named_entity(turn.players, player_id, "player")


def starbase_for_planet(turn: TurnInfo, planet_id: int) -> Starbase | None:
    """Return the starbase orbiting this planet, if this RST has one.

    Lookup is by ``starbase.planetid``, not RST ``starbase.id``.
    """
    for starbase in turn.starbases:
        if starbase.planetid == planet_id:
            return starbase
    return None
