"""JSON codec for the homeworld fleet-age input stamp."""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.fleet_age_input import (
    FleetAgeInputStamp,
    FleetAgePlayerStamp,
)
from api.errors import ValidationError


def _fleet_age_player_stamp_to_json(player: FleetAgePlayerStamp) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "playerId": player.player_id,
        "missing": player.missing,
    }
    if not player.missing:
        payload["builtTurns"] = [
            [ship_id, built_turn] for ship_id, built_turn in player.built_turns
        ]
    return payload


def fleet_age_input_stamp_to_json(stamp: FleetAgeInputStamp) -> list[dict[str, Any]]:
    return [_fleet_age_player_stamp_to_json(player) for player in stamp.players]


def _fleet_age_player_stamp_from_json(data: object) -> FleetAgePlayerStamp:
    if not isinstance(data, dict):
        raise ValidationError("homeworld fleetAgeInputStamp entries must be objects")
    player_id = data.get("playerId")
    if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id < 1:
        raise ValidationError("homeworld fleetAgeInputStamp.playerId must be an int >= 1")
    missing = data.get("missing")
    if not isinstance(missing, bool):
        raise ValidationError("homeworld fleetAgeInputStamp.missing must be a boolean")
    built_raw = data.get("builtTurns", [])
    if missing:
        if "builtTurns" in data:
            raise ValidationError(
                "homeworld fleetAgeInputStamp missing file must not include builtTurns"
            )
        return FleetAgePlayerStamp(player_id=player_id, missing=True)
    if not isinstance(built_raw, list):
        raise ValidationError("homeworld fleetAgeInputStamp.builtTurns must be an array")
    built_turns: list[tuple[int, int]] = []
    for pair in built_raw:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or isinstance(pair[0], bool)
            or isinstance(pair[1], bool)
            or not isinstance(pair[0], int)
            or not isinstance(pair[1], int)
        ):
            raise ValidationError(
                "homeworld fleetAgeInputStamp.builtTurns entries must be [shipId, builtTurn] ints"
            )
        built_turns.append((pair[0], pair[1]))
    return FleetAgePlayerStamp(
        player_id=player_id,
        missing=False,
        built_turns=tuple(sorted(built_turns)),
    )


def fleet_age_input_stamp_from_json(data: object) -> FleetAgeInputStamp:
    if not isinstance(data, list):
        raise ValidationError("homeworld fleetAgeInputStamp must be a JSON array")
    players = [_fleet_age_player_stamp_from_json(entry) for entry in data]
    player_ids = [player.player_id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValidationError("homeworld fleetAgeInputStamp playerId values must be unique")
    return FleetAgeInputStamp(players=tuple(sorted(players, key=lambda player: player.player_id)))
