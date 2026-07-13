"""Tests for early-stop hull collision census script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    HullCollisionTwinTriple,
    load_hull_collision_twins_asset,
    load_hull_collision_twins_for_category,
    parse_hull_collision_twins_document,
    twin_pairs_from_triples,
    twins_asset_to_document,
    write_hull_collision_twins_asset,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.concepts.game_category import GameCategory
from api.serialization.turn import turn_info_from_json
from early_stop_hull_collisions import (
    coerce_settings_for_category,
    first_full_hulls_policy_step,
    format_census_text,
    parse_game_type,
    run_collision_census,
    ship_only_objective,
    twin_triples_from_census,
    twins_asset_from_census,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "packages" / "api" / "tests" / "fixtures" / "inference_corpus"
TURN5_PATH = FIXTURES_ROOT / "628580" / "1" / "turns" / "3.json"
INFO_PATH = FIXTURES_ROOT / "628580" / "info.json"
# Prefer a turn that exists in the slim fixture set; fall back to .data when present.
DATA_TURN5 = REPO_ROOT / ".data" / "games" / "628580" / "11" / "turns" / "5.json"


def _load_turn() -> tuple[object, int, int]:
    if DATA_TURN5.is_file():
        info = json.loads((REPO_ROOT / ".data" / "games" / "628580" / "info.json").read_text())
        turn = turn_info_from_json(
            json.loads(DATA_TURN5.read_text()),
            settings_defaults=info.get("settings"),
        )
        return turn, 628580, 5
    settings_defaults = json.loads(INFO_PATH.read_text())["settings"]
    turn = turn_info_from_json(
        json.loads(TURN5_PATH.read_text()),
        settings_defaults=settings_defaults,
    )
    return turn, 628580, 3


def test_parse_game_type_accepts_known_categories() -> None:
    assert parse_game_type("standard") == GameCategory.STANDARD
    assert parse_game_type("EPIC") == GameCategory.EPIC


def test_parse_game_type_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown game type"):
        parse_game_type("mega")


def test_coerce_settings_for_category_shapes_standard_and_epic() -> None:
    turn, _, _ = _load_turn()
    standard = coerce_settings_for_category(turn.settings, GameCategory.STANDARD)
    epic = coerce_settings_for_category(turn.settings, GameCategory.EPIC)
    assert GameCategory.from_game_settings(standard) == GameCategory.STANDARD
    assert GameCategory.from_game_settings(epic) == GameCategory.EPIC
    assert epic.shiplimit >= 500


def test_first_full_hulls_policy_step_is_widen_hulls() -> None:
    step = first_full_hulls_policy_step(resolve_tier_policies())
    assert step.id == "widen_hulls"
    assert step.filters.hulls.all is True


def test_ship_only_objective_is_negative_penalty() -> None:
    assert ship_only_objective(-526, max_combo_weight=-355) == -171


def test_birds_epic_census_includes_resolute_allowlist_member() -> None:
    turn, game_id, host_turn = _load_turn()
    # Fixture turn 3 may lack full player roster race coverage; require Birds player.
    if not any(player.raceid == 3 for player in turn.players):
        pytest.skip("catalog turn has no Birds player")

    # 628580 is an epic game; use epic priors to match production inference.
    census = run_collision_census(
        turn,
        game_type=GameCategory.EPIC,
        catalog_game_id=game_id,
        catalog_host_turn=host_turn,
        catalog_perspective=getattr(turn.player, "id", 1),
        catalog_native_game_type=GameCategory.EPIC,
        race_ids=(3,),
    )
    assert census.game_type == "epic"
    assert census.prior_asset_path.endswith("prior_weights_epic.yaml")
    assert census.early_policy_step_id == "early_game_bands"
    assert census.widen_hulls_policy_step_id == "widen_hulls"
    assert 31 in census.allowlist_hull_ids

    birds = census.races[0]
    collision_2749 = next(
        (item for item in birds.collisions if item.military_change == 2749),
        None,
    )
    assert collision_2749 is not None
    assert any(member.hull_id == 30 for member in collision_2749.early_trigger_members)
    assert any(member.hull_id == 31 for member in collision_2749.high_tech_members)
    valiant = next(
        member for member in collision_2749.early_trigger_members if member.hull_id == 30
    )
    assert valiant.ship_only_objective is not None
    assert valiant.ship_only_objective >= census.early_stop_min_plausibility

    text = format_census_text(census)
    assert "Resolute Class Battlecruiser" in text
    assert "Suggested early-tier hull allowlist" in text


def test_birds_epic_twin_triples_include_resolute_and_dark_wing() -> None:
    turn, game_id, host_turn = _load_turn()
    if not any(player.raceid == 3 for player in turn.players):
        pytest.skip("catalog turn has no Birds player")

    census = run_collision_census(
        turn,
        game_type=GameCategory.EPIC,
        catalog_game_id=game_id,
        catalog_host_turn=host_turn,
        catalog_perspective=getattr(turn.player, "id", 1),
        catalog_native_game_type=GameCategory.EPIC,
        race_ids=(3,),
    )
    triples = twin_triples_from_census(census)
    assert HullCollisionTwinTriple(30, 31, 2749) in triples
    assert HullCollisionTwinTriple(30, 29, 3281) in triples
    # 2749 must not also admit Dark Wing; 3281 must not also admit Resolute.
    assert HullCollisionTwinTriple(30, 29, 2749) not in triples
    assert HullCollisionTwinTriple(30, 31, 3281) not in triples

    pairs = twin_pairs_from_triples(triples)
    assert (30, 31) in {(pair.low_hull_id, pair.high_hull_id) for pair in pairs}
    assert (30, 29) in {(pair.low_hull_id, pair.high_hull_id) for pair in pairs}


def test_write_twin_asset_round_trip(tmp_path: Path) -> None:
    turn, game_id, host_turn = _load_turn()
    if not any(player.raceid == 3 for player in turn.players):
        pytest.skip("catalog turn has no Birds player")

    census = run_collision_census(
        turn,
        game_type=GameCategory.EPIC,
        catalog_game_id=game_id,
        catalog_host_turn=host_turn,
        catalog_perspective=getattr(turn.player, "id", 1),
        catalog_native_game_type=GameCategory.EPIC,
        race_ids=(3,),
    )
    asset = twins_asset_from_census(census)
    out_path = tmp_path / "hull_collision_twins_epic.yaml"
    write_hull_collision_twins_asset(out_path, asset)
    loaded = load_hull_collision_twins_asset(out_path)
    assert loaded.category == GameCategory.EPIC
    assert HullCollisionTwinTriple(30, 31, 2749) in loaded.triples
    assert HullCollisionTwinTriple(30, 29, 3281) in loaded.triples
    assert loaded.pairs == twin_pairs_from_triples(loaded.triples)
    assert parse_hull_collision_twins_document(twins_asset_to_document(loaded)) == loaded


def test_checked_in_epic_twin_asset_includes_birds_collision_cases() -> None:
    asset, path = load_hull_collision_twins_for_category(GameCategory.EPIC)
    assert path.name == "hull_collision_twins_epic.yaml"
    assert HullCollisionTwinTriple(30, 31, 2749) in asset.triples
    assert HullCollisionTwinTriple(30, 29, 3281) in asset.triples
