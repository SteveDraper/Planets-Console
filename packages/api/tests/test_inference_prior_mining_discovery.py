"""Tests for prior mining pattern config and discovery helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from api.analytics.military_score_inference.prior_mining.dates import (
    parse_planets_host_date,
)
from api.analytics.military_score_inference.prior_mining.discovery import (
    discover_games_for_pattern,
    list_finished_game_candidates,
)
from api.analytics.military_score_inference.prior_mining.patterns import (
    parse_prior_mining_patterns_document,
)
from api.concepts.game_category import GameCategory


def test_parse_planets_host_date_accepts_upstream_format():
    assert parse_planets_host_date("10/26/2024 9:02:31 AM").isoformat() == "2024-10-26"


def test_parse_prior_mining_patterns_document():
    config = parse_prior_mining_patterns_document(
        {
            "version": 1,
            "patterns": [
                {
                    "id": "standard-v1",
                    "game_category": "standard",
                    "max_games": 3,
                    "min_difficulty": 1.0,
                    "earliest_date": "2024-01-01",
                }
            ],
        }
    )
    assert config.version == 1
    assert config.patterns[0].game_category == GameCategory.STANDARD


def test_list_finished_game_candidates_filters_and_sorts():
    planets = MagicMock()
    planets.games_list.return_value = [
        {
            "id": 100,
            "difficulty": 2.0,
            "datecreated": "1/1/2024 12:00:00 PM",
            "dateended": "6/1/2024 12:00:00 PM",
        },
        {
            "id": 50,
            "difficulty": 2.0,
            "datecreated": "1/1/2024 12:00:00 PM",
            "dateended": "7/1/2024 12:00:00 PM",
        },
        {
            "id": 75,
            "difficulty": 2.0,
            "datecreated": "1/1/2023 12:00:00 PM",
            "dateended": "7/1/2024 12:00:00 PM",
        },
    ]
    candidates = list_finished_game_candidates(
        planets,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )
    assert [candidate.game_id for candidate in candidates] == [50, 100]


def test_discover_games_for_pattern_resolves_category_via_loadinfo():
    planets = MagicMock()
    planets.games_list.return_value = [
        {
            "id": 628580,
            "difficulty": 2.0,
            "datecreated": "10/26/2024 9:02:31 AM",
            "dateended": "6/23/2025 2:53:43 PM",
        }
    ]
    planets.load_game_info.return_value = json.loads(
        (Path(__file__).resolve().parent / "fixtures/inference_corpus/628580/info.json").read_text(
            encoding="utf-8"
        )
    )

    from api.analytics.military_score_inference.prior_mining.patterns import PriorMiningPattern

    pattern = PriorMiningPattern(
        id="epic-test",
        game_category=GameCategory.EPIC,
        max_games=1,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )
    result = discover_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=frozenset(),
        pattern_contributed_count=0,
        max_selections=1,
    )
    assert result.games_attempted == (628580,)


def test_discover_games_for_pattern_skips_loadinfo_upstream_error():
    planets = MagicMock()
    planets.games_list.return_value = [
        {
            "id": 100,
            "difficulty": 2.0,
            "datecreated": "10/26/2024 9:02:31 AM",
            "dateended": "6/23/2025 2:53:43 PM",
        },
        {
            "id": 628580,
            "difficulty": 2.0,
            "datecreated": "10/26/2024 9:02:31 AM",
            "dateended": "6/23/2025 2:53:43 PM",
        },
    ]

    from api.analytics.military_score_inference.prior_mining.patterns import PriorMiningPattern
    from api.errors import UpstreamPlanetsError

    def load_info(game_id: int):
        if game_id == 100:
            raise UpstreamPlanetsError("Planets.nu load game info request failed.")
        return json.loads(
            (
                Path(__file__).resolve().parent / "fixtures/inference_corpus/628580/info.json"
            ).read_text(encoding="utf-8")
        )

    planets.load_game_info.side_effect = load_info

    pattern = PriorMiningPattern(
        id="epic-test",
        game_category=GameCategory.EPIC,
        max_games=1,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )
    result = discover_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=frozenset(),
        pattern_contributed_count=0,
        max_selections=1,
    )
    assert result.games_attempted == (628580,)


def test_discover_games_for_pattern_skips_dogfight_with_fewer_than_eleven_players():
    planets = MagicMock()
    planets.games_list.return_value = [
        {
            "id": 645527,
            "difficulty": 2.0,
            "datecreated": "10/26/2024 9:02:31 AM",
            "dateended": "6/23/2025 2:53:43 PM",
        }
    ]
    info = json.loads(
        (Path(__file__).resolve().parent / "fixtures/inference_corpus/628580/info.json").read_text(
            encoding="utf-8"
        )
    )
    info["players"] = info["players"][:8]
    planets.load_game_info.return_value = info

    from api.analytics.military_score_inference.prior_mining.patterns import PriorMiningPattern

    pattern = PriorMiningPattern(
        id="epic-test",
        game_category=GameCategory.EPIC,
        max_games=1,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )
    result = discover_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=frozenset(),
        pattern_contributed_count=0,
        max_selections=1,
    )
    assert result.games_attempted == ()


def test_discover_games_for_pattern_skips_already_contributed():
    planets = MagicMock()
    planets.games_list.return_value = [
        {
            "id": 628580,
            "difficulty": 2.0,
            "datecreated": "10/26/2024 9:02:31 AM",
            "dateended": "6/23/2025 2:53:43 PM",
        }
    ]
    from api.analytics.military_score_inference.prior_mining.patterns import PriorMiningPattern

    pattern = PriorMiningPattern(
        id="standard-test",
        game_category=GameCategory.STANDARD,
        max_games=1,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )
    result = discover_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=frozenset({628580}),
        pattern_contributed_count=0,
        max_selections=1,
    )
    assert result.games_attempted == ()
    assert result.already_contributed >= 1
    planets.load_game_info.assert_not_called()
