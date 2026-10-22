"""Pack a Territory movie from stored turns.

The page inflates two gzip blobs. This module does not build HTML.
"""

from __future__ import annotations

import base64
import gzip
import struct
from collections.abc import Mapping, Sequence

from api.analytics.team_territory import (
    MapRectangle,
    league_team_id_by_player,
    nu_map_rectangle,
    territory_sections,
)
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.transport.territory_movie import (
    TerritoryMovieLegendEntry,
    TerritoryMovieRectangle,
    TerritoryMovieResponse,
)

_GRID_PER_LY = 10
_UINT16_MAX = 0xFFFF


def quantize_offset(coord: float, origin: float) -> int:
    """Tenth-light-year offset from ``origin``. Python 3 ``round``, ties to even."""
    return int(round((coord - origin) * _GRID_PER_LY))


def build_territory_movie(
    turns: Sequence[TurnInfo],
    *,
    player_names: Mapping[int, str | None],
    team_names: Mapping[int, str | None],
) -> TerritoryMovieResponse:
    """Pack host turns 1 through the last turn. ``turns`` must already be that span."""
    _require_span(turns)
    rectangle = _shared_rectangle(turns)
    player_ids, team_ids = _owning_ids(turns)
    return TerritoryMovieResponse(
        turn=turns[-1].settings.turn,
        rectangle=TerritoryMovieRectangle(
            left=rectangle.left,
            bottom=rectangle.bottom,
            width=rectangle.width,
            height=rectangle.height,
        ),
        rings=_gzip_base64(_pack_rings(turns, rectangle)),
        planets=_gzip_base64(_pack_planets(turns)),
        players=_legend(player_ids, player_names),
        teams=_legend(team_ids, team_names),
    )


def _require_span(turns: Sequence[TurnInfo]) -> None:
    if not turns:
        raise ValidationError(
            "Territory movie requires stored host turns 1 through the game's current turn."
        )
    numbers = [turn.settings.turn for turn in turns]
    expected = list(range(1, len(turns) + 1))
    if numbers != expected:
        raise ValidationError(
            "Territory movie requires stored host turns 1 through "
            f"{expected[-1] if expected else 0} with no gaps; found {numbers}."
        )


def _shared_rectangle(turns: Sequence[TurnInfo]) -> MapRectangle:
    first = turns[0].settings
    for turn in turns[1:]:
        settings = turn.settings
        if (
            settings.mapwidth != first.mapwidth
            or settings.mapheight != first.mapheight
            or settings.sphere != first.sphere
        ):
            raise ValidationError("Territory movie turns do not share one map rectangle.")
    return nu_map_rectangle(first.mapwidth, first.mapheight)


def _owning_ids(turns: Sequence[TurnInfo]) -> tuple[set[int], set[int]]:
    """Players and league teams that own a planet on any turn. Id 0 is omitted."""
    player_ids: set[int] = set()
    team_ids: set[int] = set()
    for turn in turns:
        by_player = league_team_id_by_player(turn)
        for planet in turn.planets:
            if planet.ownerid <= 0:
                continue
            player_ids.add(planet.ownerid)
            team_id = by_player.get(planet.ownerid, 0)
            if team_id > 0:
                team_ids.add(team_id)
    return player_ids, team_ids


def _legend(
    owner_ids: set[int],
    names: Mapping[int, str | None],
) -> list[TerritoryMovieLegendEntry]:
    entries: list[TerritoryMovieLegendEntry] = []
    for owner_id in sorted(owner_ids):
        raw = names.get(owner_id)
        stripped = raw.strip() if isinstance(raw, str) else ""
        entries.append(
            TerritoryMovieLegendEntry(id=owner_id, name=stripped or None),
        )
    return entries


def _pack_rings(turns: Sequence[TurnInfo], rectangle: MapRectangle) -> bytes:
    """Pack ``territory_sections`` in the order that function returns."""
    per_turn = [territory_sections(turn) for turn in turns]
    buffer = bytearray()
    for section_index in range(len(per_turn[0])):
        for turn_sections in per_turn:
            kind, components = turn_sections[section_index]
            _append_u16(buffer, len(components), label=f"{kind} component count")
            for group_id, ring in components:
                _append_u16(buffer, group_id, label=f"{kind} group id")
                _append_u16(buffer, len(ring), label=f"{kind} vertex count")
                for x, y in ring:
                    _append_u16(
                        buffer,
                        quantize_offset(x, rectangle.left),
                        label=f"{kind} dx",
                    )
                    _append_u16(
                        buffer,
                        quantize_offset(y, rectangle.bottom),
                        label=f"{kind} dy",
                    )
    return bytes(buffer)


def _pack_planets(turns: Sequence[TurnInfo]) -> bytes:
    """One row per planet id. Coordinates and ``first_turn`` come from its first sighting."""
    rows: dict[int, tuple[int, int, int]] = {}
    for turn in turns:
        host_turn = turn.settings.turn
        for planet in turn.planets:
            if planet.id in rows:
                continue
            rows[planet.id] = (planet.x, planet.y, host_turn)
    buffer = bytearray()
    _append_u16(buffer, len(rows), label="planet count")
    for planet_id in sorted(rows):
        x, y, first_turn = rows[planet_id]
        _append_u16(buffer, planet_id, label="planet id")
        _append_u16(buffer, x, label=f"planet {planet_id} x")
        _append_u16(buffer, y, label=f"planet {planet_id} y")
        _append_u16(buffer, first_turn, label=f"planet {planet_id} first_turn")
    return bytes(buffer)


def _append_u16(buffer: bytearray, value: int, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _UINT16_MAX:
        raise ValidationError(f"Territory movie {label} {value} does not fit in uint16.")
    buffer.extend(struct.pack("<H", value))


def _gzip_base64(payload: bytes) -> str:
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    return base64.b64encode(compressed).decode("ascii")
