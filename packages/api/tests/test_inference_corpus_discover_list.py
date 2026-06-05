"""Tests for inference corpus ground truth extraction and discover listings."""

import json

import pytest
from api.services.store_service import StoreService
from api.storage.file import FileStorageBackend

from tests.inference_corpus.discover_list import discover_case_listings, format_listing_report
from tests.inference_corpus.discovery import discover_cases_for_game
from tests.inference_corpus.ground_truth import describe_inventory_activity
from tests.inference_corpus.manifest import FIXTURES_ROOT
from tests.inference_corpus.storage_loader import (
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)


@pytest.fixture
def listing_storage(tmp_path):
    storage_root = tmp_path / "data"
    backend = FileStorageBackend(storage_root)
    fixture_game_root = FIXTURES_ROOT / "628580"
    backend.put("games/628580/info", json.loads((fixture_game_root / "info.json").read_text()))
    for turn_number in (2, 3):
        turn_src = fixture_game_root / "1" / "turns" / f"{turn_number}.json"
        backend.put(
            f"games/628580/1/turns/{turn_number}",
            json.loads(turn_src.read_text()),
        )
    configure_file_storage(storage_root=storage_root)
    return storage_root


def test_discover_cases_respects_host_turn_range(listing_storage):
    store = StoreService(configure_file_storage(storage_root=listing_storage))
    all_cases = discover_cases_for_game(store, 628580)
    in_range = discover_cases_for_game(store, 628580, min_host_turn=2, max_host_turn=2)
    out_of_range = discover_cases_for_game(store, 628580, min_host_turn=99, max_host_turn=99)
    assert len(all_cases) == 1
    assert [case.host_turn for case in in_range] == [2]
    assert out_of_range == []


def test_describe_inventory_activity_seed_case():
    settings = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    from api.serialization.turn import turn_info_from_json

    with open(FIXTURES_ROOT / "628580/1/turns/2.json") as handle:
        prior_turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    with open(FIXTURES_ROOT / "628580/1/turns/3.json") as handle:
        score_turn = turn_info_from_json(json.load(handle), settings_defaults=settings)

    summary = describe_inventory_activity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
    )
    assert "Missouri Class Battleship" in summary
    assert "Transwarp Drive" in summary
    assert "loaded 40x Mark 4 Photon" in summary
    assert "ship fighters" not in summary


def test_discover_case_listings_human_readable(listing_storage):
    storage = configure_file_storage(storage_root=listing_storage)
    listings = discover_case_listings(
        store=StoreService(storage),
        turn_load=make_turn_load_service(storage),
        game_service=make_game_service(storage),
        game_id=628580,
        min_host_turn=2,
        max_host_turn=2,
    )
    assert len(listings) == 1
    lines = format_listing_report(listings, game_id=628580)
    joined = "\n".join(lines)
    assert "perspective 1" in joined
    assert "Missouri Class Battleship" in joined
    assert listings[0].summary
