"""Elimination detection from Planets.nu ``Player`` rows."""

from api.models.enums import PlayerStatus
from api.models.player import Player


def player_status(player: Player) -> PlayerStatus:
    """Map wire ``Player.status`` to :class:`PlayerStatus`."""
    try:
        return PlayerStatus(player.status)
    except ValueError:
        return PlayerStatus.UNKNOWN


def elimination_turn(player: Player) -> int | None:
    """Turn the player was eliminated, or ``None`` if not eliminated."""
    if player_status(player) != PlayerStatus.ELIMINATED:
        return None
    return player.statusturn


def is_eliminated_at_turn(player: Player, turn: int) -> bool:
    """``True`` when the player is eliminated on or before ``turn``."""
    death_turn = elimination_turn(player)
    return death_turn is not None and turn >= death_turn


def last_meaningful_turn(player: Player, game_latest_turn: int) -> int:
    """Last turn worth loading or selecting for this perspective."""
    death_turn = elimination_turn(player)
    if death_turn is not None:
        return death_turn
    return game_latest_turn


def required_turn_numbers(player: Player, game_latest_turn: int) -> list[int]:
    """Turn numbers that must be stored for load-all completeness and import."""
    last = last_meaningful_turn(player, game_latest_turn)
    if last < 1:
        return []
    return list(range(1, last + 1))
