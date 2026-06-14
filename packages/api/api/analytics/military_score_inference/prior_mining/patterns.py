"""Pattern config loading for the inference prior miner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from api.analytics.military_score_inference.prior_weights_asset import default_prior_weights_dir
from api.concepts.game_category import GameCategory

DEFAULT_PATTERNS_PATH = default_prior_weights_dir() / "prior_mining_patterns_standard.yaml"


@dataclass(frozen=True)
class PriorMiningPattern:
    id: str
    game_category: GameCategory
    max_games: int
    min_difficulty: float
    earliest_date: str


@dataclass(frozen=True)
class PriorMiningPatternConfig:
    version: int
    patterns: tuple[PriorMiningPattern, ...]


def default_patterns_path() -> Path:
    return DEFAULT_PATTERNS_PATH


def load_prior_mining_patterns(path: Path) -> PriorMiningPatternConfig:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"prior mining patterns root must be a mapping: {path}")
    return parse_prior_mining_patterns_document(document)


def parse_prior_mining_patterns_document(document: dict[str, Any]) -> PriorMiningPatternConfig:
    version = document.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("prior mining patterns version must be a positive integer")

    patterns_raw = document.get("patterns")
    if not isinstance(patterns_raw, list) or not patterns_raw:
        raise ValueError("patterns must be a non-empty list")

    patterns: list[PriorMiningPattern] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(patterns_raw):
        if not isinstance(row, dict):
            raise ValueError(f"patterns[{index}] must be a mapping")
        pattern_id = row.get("id")
        if not isinstance(pattern_id, str) or not pattern_id.strip():
            raise ValueError(f"patterns[{index}].id must be a non-empty string")
        if pattern_id in seen_ids:
            raise ValueError(f"duplicate pattern id {pattern_id!r}")
        seen_ids.add(pattern_id)

        category_raw = row.get("game_category")
        if not isinstance(category_raw, str):
            raise ValueError(f"patterns[{index}].game_category must be a string")
        try:
            game_category = GameCategory(category_raw)
        except ValueError as exc:
            raise ValueError(
                f"patterns[{index}].game_category is invalid: {category_raw!r}"
            ) from exc

        max_games = row.get("max_games")
        if not isinstance(max_games, int) or max_games < 1:
            raise ValueError(f"patterns[{index}].max_games must be a positive integer")

        min_difficulty = row.get("min_difficulty")
        if not isinstance(min_difficulty, (int, float)):
            raise ValueError(f"patterns[{index}].min_difficulty must be a number")

        earliest_date = row.get("earliest_date")
        if not isinstance(earliest_date, str) or not _is_iso_date(earliest_date):
            raise ValueError(
                f"patterns[{index}].earliest_date must be an ISO calendar date YYYY-MM-DD"
            )

        patterns.append(
            PriorMiningPattern(
                id=pattern_id,
                game_category=game_category,
                max_games=max_games,
                min_difficulty=float(min_difficulty),
                earliest_date=earliest_date,
            )
        )

    return PriorMiningPatternConfig(version=version, patterns=tuple(patterns))


def _is_iso_date(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3:
        return False
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return False
    return 1 <= month <= 12 and 1 <= day <= 31 and year >= 1
