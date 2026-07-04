"""Extract homeworld coordinates from stored turn-1 perspective snapshots."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from api.concepts.game_category import GameCategory
from api.models.game import GameSettings, TurnInfo
from api.models.planet import Planet
from api.models.player import Player
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from hull_catalog_analysis import discover_game_ids, perspective_slots_for_game

BASELINE_TURN = 1
DEFAULT_MIN_BASELINE_CLANS = 10_000
DEFAULT_PREFERRED_TEMP_W = 50
CRYSTAL_DESERT_PREFERRED_TEMP_W = 100
CRYSTAL_RACE_ID = 7
DESERT_WORLDS_ADVANTAGE_ID = 21

TARGET_GAME_CATEGORIES = frozenset({GameCategory.EPIC, GameCategory.STANDARD})


@dataclass(frozen=True)
class HomeworldLocation:
    player: str
    x: int
    y: int


@dataclass(frozen=True)
class GameHomeworlds:
    game_id: int
    game_type: GameCategory
    homeworlds: tuple[HomeworldLocation, ...]


@dataclass(frozen=True)
class HomeworldCsvRow:
    game_type: str
    game_id: int
    player: str
    x: int
    y: int


def active_advantage_ids(player: Player) -> frozenset[int]:
    if not player.activeadvantages.strip():
        return frozenset()
    return frozenset(
        int(part) for part in player.activeadvantages.split(",") if part.strip().isdigit()
    )


def preferred_homeworld_temp_w(*, race_id: int, active_advantages: frozenset[int]) -> int:
    if race_id == CRYSTAL_RACE_ID and DESERT_WORLDS_ADVANTAGE_ID in active_advantages:
        return CRYSTAL_DESERT_PREFERRED_TEMP_W
    return DEFAULT_PREFERRED_TEMP_W


def starbase_planet_ids(turn: TurnInfo) -> frozenset[int]:
    return frozenset(starbase.planetid for starbase in turn.starbases)


def matches_homeworld_baseline_profile(
    planet,
    *,
    turn: TurnInfo,
    settings: GameSettings,
    min_baseline_clans: int = DEFAULT_MIN_BASELINE_CLANS,
) -> bool:
    if planet.ownerid != turn.player.id:
        return False
    if planet.clans < min_baseline_clans:
        return False
    if settings.homeworldhasstarbase and planet.id not in starbase_planet_ids(turn):
        return False
    preferred_temp = preferred_homeworld_temp_w(
        race_id=turn.player.raceid,
        active_advantages=active_advantage_ids(turn.player),
    )
    return planet.temp == preferred_temp


def homeworld_planet_for_turn(turn: TurnInfo) -> Planet | None:
    """Return the homeworld planet for a turn-1 perspective snapshot, if identifiable."""
    owned_planets = [planet for planet in turn.planets if planet.ownerid == turn.player.id]
    if not owned_planets:
        return None

    baseline_matches = [
        planet
        for planet in owned_planets
        if matches_homeworld_baseline_profile(planet, turn=turn, settings=turn.settings)
    ]
    if len(baseline_matches) == 1:
        return baseline_matches[0]
    if len(baseline_matches) > 1:
        return max(baseline_matches, key=lambda planet: planet.clans)

    if len(owned_planets) == 1:
        return owned_planets[0]

    with_starbase = [planet for planet in owned_planets if planet.id in starbase_planet_ids(turn)]
    if with_starbase:
        return max(with_starbase, key=lambda planet: planet.clans)

    return max(owned_planets, key=lambda planet: planet.clans)


def load_turn_file(
    storage_root: Path,
    game_id: int,
    perspective: int,
    turn_number: int,
    *,
    settings_defaults: dict,
) -> TurnInfo | None:
    turn_path = (
        storage_root / "games" / str(game_id) / str(perspective) / "turns" / f"{turn_number}.json"
    )
    if not turn_path.is_file():
        return None
    with turn_path.open() as handle:
        return turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)


def load_game_settings_defaults(storage_root: Path, game_id: int) -> dict | None:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    if not info_path.is_file():
        return None
    with info_path.open() as handle:
        return json.load(handle)["settings"]


def extract_homeworlds_for_game(
    storage_root: Path,
    game_id: int,
) -> GameHomeworlds | None:
    settings_defaults = load_game_settings_defaults(storage_root, game_id)
    if settings_defaults is None:
        return None

    info = game_info_from_json(
        json.loads((storage_root / "games" / str(game_id) / "info.json").read_text())
    )
    game_type = GameCategory.from_game_info(info)
    if game_type not in TARGET_GAME_CATEGORIES:
        return None

    homeworlds: list[HomeworldLocation] = []
    for perspective in perspective_slots_for_game(storage_root, game_id):
        if perspective < 1:
            continue
        turn = load_turn_file(
            storage_root,
            game_id,
            perspective,
            BASELINE_TURN,
            settings_defaults=settings_defaults,
        )
        if turn is None:
            continue

        planet = homeworld_planet_for_turn(turn)
        if planet is None:
            continue

        homeworlds.append(
            HomeworldLocation(
                player=turn.player.username,
                x=planet.x,
                y=planet.y,
            )
        )

    return GameHomeworlds(
        game_id=game_id,
        game_type=game_type,
        homeworlds=tuple(homeworlds),
    )


def extract_homeworlds_by_category(
    storage_root: Path,
    *,
    game_ids: Iterable[int] | None = None,
) -> dict[GameCategory, list[GameHomeworlds]]:
    selected_game_ids = list(game_ids) if game_ids is not None else discover_game_ids(storage_root)
    grouped: dict[GameCategory, list[GameHomeworlds]] = {
        GameCategory.EPIC: [],
        GameCategory.STANDARD: [],
    }

    for game_id in selected_game_ids:
        extracted = extract_homeworlds_for_game(storage_root, game_id)
        if extracted is None:
            continue
        grouped[extracted.game_type].append(extracted)

    for game_type in grouped:
        grouped[game_type].sort(key=lambda item: item.game_id)

    return grouped


def homeworld_rows_for_games(games: Iterable[GameHomeworlds]) -> list[HomeworldCsvRow]:
    rows: list[HomeworldCsvRow] = []
    for game in games:
        for homeworld in game.homeworlds:
            rows.append(
                HomeworldCsvRow(
                    game_type=game.game_type.value,
                    game_id=game.game_id,
                    player=homeworld.player,
                    x=homeworld.x,
                    y=homeworld.y,
                )
            )
    return rows


def flatten_homeworld_rows(
    grouped: dict[GameCategory, list[GameHomeworlds]],
) -> list[HomeworldCsvRow]:
    rows: list[HomeworldCsvRow] = []
    for game_type in (GameCategory.EPIC, GameCategory.STANDARD):
        rows.extend(homeworld_rows_for_games(grouped.get(game_type, [])))
    return rows


def write_homeworld_csv(rows: Iterable[HomeworldCsvRow], output: TextIO) -> None:
    writer = csv.DictWriter(
        output,
        fieldnames=["game_type", "game_id", "player", "x", "y"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "game_type": row.game_type,
                "game_id": row.game_id,
                "player": row.player,
                "x": row.x,
                "y": row.y,
            }
        )
