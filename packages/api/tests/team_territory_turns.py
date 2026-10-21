"""Synthetic turns for Territory geometry tests."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.team_territory import nu_map_rectangle
from api.models.game import TurnInfo
from api.models.player import Player

from tests.homeworld_locator_test_helpers import _planet, load_sample_turn


def _roster_player(template: Player, *, player_id: int, league_team_id: int) -> Player:
    return replace(
        template,
        id=player_id,
        username=f"player-{player_id}",
        leagueteamid=league_team_id,
    )


def territory_turn(
    sites: list[tuple[int, int, int, int, int]],
    *,
    sphere: bool,
    width: int,
    height: int,
    mapshape: int = 4,
    maptype: int = 7,
    host_turn: int | None = None,
) -> TurnInfo:
    """sites are (planet_id, x, y, owner_id, league_team_id) in rectangle-local coordinates.

    owner_id 0 is unowned. Local (0, 0) is the lower-left of the Nu-centered rectangle.
    ``host_turn`` sets ``settings.turn`` when the span position matters.
    """
    turn = load_sample_turn()
    planet_template = turn.planets[0]
    player_template = turn.players[0]
    rectangle = nu_map_rectangle(width, height)
    planets = []
    players_by_id: dict[int, Player] = {}
    for planet_id, x, y, owner_id, league_team_id in sites:
        planets.append(
            _planet(
                planet_template,
                planet_id=planet_id,
                x=round(x + rectangle.left),
                y=round(y + rectangle.bottom),
                ownerid=owner_id,
            )
        )
        if owner_id != 0 and owner_id not in players_by_id:
            players_by_id[owner_id] = _roster_player(
                player_template,
                player_id=owner_id,
                league_team_id=league_team_id,
            )
    players = [players_by_id[player_id] for player_id in sorted(players_by_id)]
    settings = replace(
        turn.settings,
        sphere=sphere,
        mapwidth=width,
        mapheight=height,
        mapshape=mapshape,
    )
    if host_turn is not None:
        settings = replace(settings, turn=host_turn)
    return replace(
        turn,
        planets=planets,
        players=players,
        player=players[0],
        settings=settings,
        game=replace(turn.game, maptype=maptype),
    )
