"""Finished-game discovery for inference prior mining."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import dacite

from api.concepts.game_category import GameCategory
from api.errors import ValidationError
from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_from_json
from api.services.storage_json import require_dict

from .dates import parse_iso_calendar_date, parse_planets_host_date
from .log import LOGGER
from .patterns import PriorMiningPattern


@dataclass(frozen=True)
class DiscoveredGameCandidate:
    game_id: int
    difficulty: float
    date_created: str
    date_ended: str


@dataclass
class PatternDiscoveryCounters:
    candidates_examined: int = 0
    category_mismatches: int = 0
    already_contributed: int = 0


@dataclass(frozen=True)
class PatternDiscoveryResult:
    pattern_id: str
    game_category: GameCategory
    candidates_examined: int
    category_mismatches: int
    already_contributed: int
    games_attempted: tuple[int, ...]
    games_rejected: tuple[int, ...]
    games_added: tuple[int, ...]
    slots_remaining: int


def list_finished_game_candidates(
    planets: PlanetsNuClient,
    *,
    min_difficulty: float,
    earliest_date: str,
) -> list[DiscoveredGameCandidate]:
    earliest = parse_iso_calendar_date(earliest_date)
    candidates: list[DiscoveredGameCandidate] = []
    for row in planets.games_list(status=3, scope=0):
        candidate = _parse_list_row(row)
        if candidate is None:
            continue
        if candidate.difficulty < min_difficulty:
            continue
        try:
            created = parse_planets_host_date(candidate.date_created)
        except ValueError:
            continue
        if created < earliest:
            continue
        candidates.append(candidate)

    candidates.sort(key=lambda item: item.game_id)
    candidates.sort(key=lambda item: _sortable_end_date(item.date_ended), reverse=True)
    LOGGER.info(
        "discovery list filter: %s candidates after difficulty/date filters",
        len(candidates),
    )
    return candidates


def iter_accepted_games_for_pattern(
    pattern: PriorMiningPattern,
    *,
    planets: PlanetsNuClient,
    contributing_game_ids: frozenset[int],
    counters: PatternDiscoveryCounters,
    attempted_game_ids: set[int] | None = None,
) -> Iterator[int]:
    """Yield game ids that match the pattern category, updating ``counters`` in place."""
    seen_attempts = attempted_game_ids if attempted_game_ids is not None else set()

    for candidate in list_finished_game_candidates(
        planets,
        min_difficulty=pattern.min_difficulty,
        earliest_date=pattern.earliest_date,
    ):
        counters.candidates_examined += 1
        if candidate.game_id in contributing_game_ids or candidate.game_id in seen_attempts:
            counters.already_contributed += 1
            LOGGER.info(
                "pattern %s: skip game %s (already contributed or attempted)",
                pattern.id,
                candidate.game_id,
            )
            continue

        remote = planets.load_game_info(candidate.game_id)
        try:
            info = game_info_from_json(require_dict(remote, f"game info {candidate.game_id}"))
        except (ValidationError, dacite.DaciteError) as exc:
            LOGGER.warning(
                "pattern %s: reject game %s (invalid loadinfo: %s)",
                pattern.id,
                candidate.game_id,
                exc,
            )
            continue
        resolved = GameCategory.from_game_settings(info.settings)
        if resolved != pattern.game_category:
            counters.category_mismatches += 1
            LOGGER.info(
                "pattern %s: reject game %s (category %s != %s)",
                pattern.id,
                candidate.game_id,
                resolved.value,
                pattern.game_category.value,
            )
            continue
        LOGGER.info(
            "pattern %s: accept game %s for mining",
            pattern.id,
            candidate.game_id,
        )
        yield candidate.game_id


def discover_games_for_pattern(
    pattern: PriorMiningPattern,
    *,
    planets: PlanetsNuClient,
    contributing_game_ids: frozenset[int],
    pattern_contributed_count: int,
    max_selections: int,
) -> PatternDiscoveryResult:
    """Select up to ``max_selections`` category-matching games without mining them."""
    counters = PatternDiscoveryCounters()
    selected: list[int] = []
    for game_id in iter_accepted_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=contributing_game_ids,
        counters=counters,
        attempted_game_ids=set(selected),
    ):
        selected.append(game_id)
        if len(selected) >= max_selections:
            break

    target = max(0, pattern.max_games - pattern_contributed_count)
    return PatternDiscoveryResult(
        pattern_id=pattern.id,
        game_category=pattern.game_category,
        candidates_examined=counters.candidates_examined,
        category_mismatches=counters.category_mismatches,
        already_contributed=counters.already_contributed,
        games_attempted=tuple(selected),
        games_rejected=(),
        games_added=(),
        slots_remaining=max(0, target - len(selected)),
    )


def _parse_list_row(row: dict[str, Any]) -> DiscoveredGameCandidate | None:
    game_id = row.get("id")
    if not isinstance(game_id, int):
        return None
    difficulty = row.get("difficulty")
    if not isinstance(difficulty, (int, float)):
        return None
    date_created = row.get("datecreated")
    date_ended = row.get("dateended")
    if not isinstance(date_created, str) or not isinstance(date_ended, str):
        return None
    return DiscoveredGameCandidate(
        game_id=game_id,
        difficulty=float(difficulty),
        date_created=date_created,
        date_ended=date_ended,
    )


def _sortable_end_date(date_ended: str) -> tuple[int, int, int]:
    try:
        parsed = parse_planets_host_date(date_ended)
    except ValueError:
        return (0, 0, 0)
    return (parsed.year, parsed.month, parsed.day)
