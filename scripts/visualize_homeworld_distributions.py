#!/usr/bin/env python3
"""Compute homeworld distance distributions from sampled_homeworlds.csv."""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import typer
from api.concepts.game_category import STANDARD_EPIC_PLAYER_COUNT, GameCategory
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from hull_catalog_analysis import perspective_slots_for_game

app = typer.Typer(
    add_completion=False,
    help="Compute clockwise-neighbor and map-center distance distributions per game type.",
)

DEFAULT_CSV = Path("local/sampled_homeworlds.csv")
DEFAULT_STORAGE_ROOT = Path(".sampler_data")
DEFAULT_UNIVERSE_CENTER = (2000.0, 2000.0)
BASELINE_TURN = 1
NEIGHBOR_BIN_WIDTH_LY = 10
CENTER_BIN_WIDTH_LY = 10
TARGET_GAME_CATEGORIES = frozenset({GameCategory.EPIC, GameCategory.STANDARD})


def _resolved_game_type(storage_root: Path, game_id: int) -> GameCategory | None:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    if not info_path.is_file():
        return None
    info = game_info_from_json(json.loads(info_path.read_text()))
    game_type = GameCategory.from_game_info(info)
    if game_type not in TARGET_GAME_CATEGORIES:
        return None
    return game_type


def _homeworld_bbox_center(homeworlds: list[tuple[int, int]]) -> tuple[float, float] | None:
    if not homeworlds:
        return None
    xs = [x_coord for x_coord, _ in homeworlds]
    ys = [y_coord for _, y_coord in homeworlds]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _planet_bbox_center(
    storage_root: Path,
    game_id: int,
    *,
    turn_number: int = BASELINE_TURN,
) -> tuple[float, float] | None:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    if not info_path.is_file():
        return None

    raw = json.loads(info_path.read_text())
    settings_defaults = raw["settings"]
    unique_planets: dict[int, tuple[int, int]] = {}
    for perspective in perspective_slots_for_game(storage_root, game_id):
        turn_path = (
            storage_root
            / "games"
            / str(game_id)
            / str(perspective)
            / "turns"
            / f"{turn_number}.json"
        )
        if not turn_path.is_file():
            continue
        turn = turn_info_from_json(
            json.loads(turn_path.read_text()),
            settings_defaults=settings_defaults,
        )
        for planet in turn.planets:
            unique_planets[planet.id] = (planet.x, planet.y)

    if len(unique_planets) < 2:
        return None

    xs = [x_coord for x_coord, _ in unique_planets.values()]
    ys = [y_coord for _, y_coord in unique_planets.values()]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _game_center(
    storage_root: Path,
    game_id: int,
    homeworlds: list[tuple[int, int]],
    cache: dict[int, tuple[tuple[float, float], str]],
) -> tuple[float, float]:
    if game_id in cache:
        return cache[game_id][0]

    center = _planet_bbox_center(storage_root, game_id)
    source = "planet_bbox"
    if center is None:
        center = _homeworld_bbox_center(homeworlds)
        source = "homeworld_bbox"
    if center is None:
        center = DEFAULT_UNIVERSE_CENTER
        source = "fixed_2000"

    cache[game_id] = (center, source)
    return center


def _distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _clockwise_neighbor_distances(
    homeworlds: list[tuple[int, int]],
    *,
    center_x: float,
    center_y: float,
) -> list[float]:
    if len(homeworlds) < 2:
        return []
    ordered = sorted(
        homeworlds,
        key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x),
        reverse=True,
    )
    distances: list[float] = []
    for index, point in enumerate(ordered):
        neighbor = ordered[(index + 1) % len(ordered)]
        distances.append(_distance(point, neighbor))
    return distances


def _histogram(
    values: list[float],
    *,
    bin_width: int,
    max_edge: float,
) -> tuple[list[str], list[int]]:
    if not values:
        return [], []
    bin_count = max(1, int(math.ceil(max_edge / bin_width)))
    counts = [0] * bin_count
    for value in values:
        index = min(int(value // bin_width), bin_count - 1)
        counts[index] += 1
    labels = [f"{index * bin_width}-{(index + 1) * bin_width}" for index in range(bin_count)]
    return labels, counts


def _summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return {"n": 0, "mean": 0, "p25": 0, "p50": 0, "p75": 0, "min": 0, "max": 0}

    def percentile(fraction: float) -> float:
        return ordered[min(count - 1, int(fraction * count))]

    return {
        "n": count,
        "mean": round(sum(ordered) / count, 1),
        "p25": round(percentile(0.25), 1),
        "p50": round(percentile(0.5), 1),
        "p75": round(percentile(0.75), 1),
        "min": round(ordered[0], 1),
        "max": round(ordered[-1], 1),
    }


def build_distribution_report(
    *,
    csv_path: Path,
    storage_root: Path,
) -> dict:
    games: dict[int, list[tuple[int, int]]] = defaultdict(list)
    with csv_path.open() as handle:
        for row in csv.DictReader(handle):
            games[int(row["game_id"])].append((int(row["x"]), int(row["y"])))

    center_cache: dict[int, tuple[tuple[float, float], str]] = {}
    center_sources: dict[str, int] = defaultdict(int)
    neighbor_distances: dict[str, list[float]] = defaultdict(list)
    center_distances: dict[str, list[float]] = defaultdict(list)
    games_with_neighbor_samples: dict[str, int] = defaultdict(int)
    games_skipped_by_category: int = 0

    for game_id, homeworlds in games.items():
        game_type = _resolved_game_type(storage_root, game_id)
        if game_type is None:
            games_skipped_by_category += 1
            continue

        center_x, center_y = _game_center(storage_root, game_id, homeworlds, center_cache)
        _, center_source = center_cache[game_id]
        center_sources[center_source] += 1
        category_key = game_type.value

        for x_coord, y_coord in homeworlds:
            center_distances[category_key].append(
                math.hypot(x_coord - center_x, y_coord - center_y)
            )

        clockwise = _clockwise_neighbor_distances(
            homeworlds,
            center_x=center_x,
            center_y=center_y,
        )
        if clockwise:
            games_with_neighbor_samples[category_key] += 1
            neighbor_distances[category_key].extend(clockwise)

    neighbor_max = max(
        max(neighbor_distances["epic"], default=0.0),
        max(neighbor_distances["standard"], default=0.0),
    )
    center_max = max(
        max(center_distances["epic"], default=0.0),
        max(center_distances["standard"], default=0.0),
    )

    neighbor_labels, neighbor_epic = _histogram(
        neighbor_distances["epic"],
        bin_width=NEIGHBOR_BIN_WIDTH_LY,
        max_edge=neighbor_max,
    )
    _, neighbor_standard = _histogram(
        neighbor_distances["standard"],
        bin_width=NEIGHBOR_BIN_WIDTH_LY,
        max_edge=neighbor_max,
    )
    center_labels, center_epic = _histogram(
        center_distances["epic"],
        bin_width=CENTER_BIN_WIDTH_LY,
        max_edge=center_max,
    )
    _, center_standard = _histogram(
        center_distances["standard"],
        bin_width=CENTER_BIN_WIDTH_LY,
        max_edge=center_max,
    )

    return {
        "source": str(csv_path),
        "storage_root": str(storage_root),
        "method": {
            "map_center": (
                "Per game: center of the planet point-cloud bounding box from turn 1, "
                "unioning unique planets across all stored player perspectives "
                "(deduped by planet id). Fallback: homeworld-only bbox center, then "
                f"fixed {DEFAULT_UNIVERSE_CENTER}."
            ),
            "clockwise_neighbor": (
                "Sort homeworlds by angle from the per-game map center (atan2), descending "
                "(clockwise); Euclidean distance to the next homeworld on the ring."
            ),
            "center_distance": (
                "Euclidean distance from each homeworld to the per-game map center above."
            ),
            "games_skipped": (
                "Games with fewer than 2 homeworld rows omit clockwise-neighbor samples."
            ),
            "category_filter": (
                "Only games classified as epic or standard via GameCategory.from_game_info "
                f"(shape rules plus exactly {STANDARD_EPIC_PLAYER_COUNT} players) are included."
            ),
        },
        "center_sources": dict(center_sources),
        "games_skipped_by_category": games_skipped_by_category,
        "games_with_neighbor_samples": dict(games_with_neighbor_samples),
        "neighbor_bin_width_ly": NEIGHBOR_BIN_WIDTH_LY,
        "center_bin_width_ly": CENTER_BIN_WIDTH_LY,
        "neighbor": {
            "categories": neighbor_labels,
            "epic": neighbor_epic,
            "standard": neighbor_standard,
            "summary": {
                game_type: _summary(neighbor_distances[game_type])
                for game_type in ("epic", "standard")
            },
        },
        "center": {
            "categories": center_labels,
            "epic": center_epic,
            "standard": center_standard,
            "summary": {
                game_type: _summary(center_distances[game_type])
                for game_type in ("epic", "standard")
            },
        },
    }


@app.callback(invoke_without_command=True)
def run_command(
    ctx: typer.Context,
    csv_path: Path = typer.Option(
        DEFAULT_CSV,
        "--csv",
        help="Homeworld CSV produced by extract_homeworlds.py.",
    ),
    storage_root: Path = typer.Option(
        DEFAULT_STORAGE_ROOT,
        "--storage-root",
        help="File backend root for turn-1 planet snapshots (info.json + turns).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write distribution JSON to this file (stdout when omitted).",
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    if not csv_path.is_file():
        typer.echo(f"CSV not found: {csv_path}", err=True)
        raise typer.Exit(code=2)

    report = build_distribution_report(csv_path=csv_path, storage_root=storage_root)
    payload = json.dumps(report, indent=2)

    if output is None:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload if payload.endswith("\n") else payload + "\n")
    typer.echo(f"wrote distribution report to {output}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
