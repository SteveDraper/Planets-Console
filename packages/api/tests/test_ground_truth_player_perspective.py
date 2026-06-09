"""Ground truth must use the ship owner's perspective, not the viewer's."""

from pathlib import Path

import pytest
from api.services.store_service import StoreService

from tests.inference_corpus.case_helpers import score_for_player
from tests.inference_corpus.ground_truth import (
    extract_ground_truth_for_player,
    extract_ground_truth_v1,
    format_ground_truth_summary,
)
from tests.inference_corpus.models import DiscoveredCase
from tests.inference_corpus.storage_loader import (
    configure_file_storage,
    load_ground_truth_turn_snapshots,
    make_game_service,
    make_turn_load_service,
)

_DATA_ROOT = Path(__file__).resolve().parents[3] / ".data"
_GAME_ID = 673864
_PLAYER_ID = 1
_HOST_TURN = 2


@pytest.mark.skipif(
    not (_DATA_ROOT / "games" / str(_GAME_ID) / "1" / "turns" / "3.json").is_file(),
    reason="local game 673864 store only",
)
def test_ground_truth_turn_snapshots_use_player_perspective_not_spectator():
    storage = configure_file_storage(storage_root=_DATA_ROOT)
    turn_load = make_turn_load_service(storage)
    game_info = make_game_service(storage).get_game_info(_GAME_ID)

    spectator_prior, spectator_score = (
        turn_load.get_turn_info(_GAME_ID, 0, _HOST_TURN),
        turn_load.get_turn_info(_GAME_ID, 0, _HOST_TURN + 1),
    )
    owner_prior, owner_score = load_ground_truth_turn_snapshots(
        turn_load,
        game_info,
        _GAME_ID,
        _PLAYER_ID,
        _HOST_TURN,
    )

    wrong = extract_ground_truth_v1(
        prior_turn=spectator_prior,
        score_turn=spectator_score,
        player_id=_PLAYER_ID,
        score=score_for_player(spectator_score.scores, _PLAYER_ID, "test"),
        complexity="minimal",
    )
    right = extract_ground_truth_for_player(
        turn_load=turn_load,
        game_info=game_info,
        game_id=_GAME_ID,
        player_id=_PLAYER_ID,
        host_turn=_HOST_TURN,
        score=score_for_player(owner_score.scores, _PLAYER_ID, "test"),
        complexity="minimal",
    )

    assert wrong.available is True
    assert wrong.ground_truth == (("combo_2065_0_none_none_0_0", 1),)
    assert right.available is True
    summary = format_ground_truth_summary(right.ground_truth, score_turn=owner_score)
    assert "Imperial Topaz Class Gunboats" in summary
    assert "Quantam Drive 7" in summary
    assert "Plasma Bolt" in summary
    assert owner_prior is not spectator_prior
    assert owner_score is not spectator_score


@pytest.mark.skipif(
    not (_DATA_ROOT / "games" / str(_GAME_ID) / "1" / "turns" / "3.json").is_file(),
    reason="local game 673864 store only",
)
def test_ground_truth_for_player_ignores_viewer_perspective_turn_files():
    storage = configure_file_storage(storage_root=_DATA_ROOT)
    turn_load = make_turn_load_service(storage)
    game_info = make_game_service(storage).get_game_info(_GAME_ID)
    viewer_score = turn_load.get_turn_info(_GAME_ID, 2, _HOST_TURN + 1)

    extraction = extract_ground_truth_for_player(
        turn_load=turn_load,
        game_info=game_info,
        game_id=_GAME_ID,
        player_id=_PLAYER_ID,
        host_turn=_HOST_TURN,
        score=score_for_player(viewer_score.scores, _PLAYER_ID, "test"),
        complexity="minimal",
    )
    summary = format_ground_truth_summary(
        extraction.ground_truth,
        score_turn=load_ground_truth_turn_snapshots(
            turn_load,
            game_info,
            _GAME_ID,
            _PLAYER_ID,
            _HOST_TURN,
        )[1],
    )
    assert "Quantam Drive 7" in summary


@pytest.mark.skipif(
    not (_DATA_ROOT / "games" / str(_GAME_ID) / "1" / "turns" / "3.json").is_file(),
    reason="local game 673864 store only",
)
def test_listing_for_case_uses_player_perspective_for_ground_truth():
    from tests.inference_corpus.discover_list import _listing_for_case

    storage = configure_file_storage(storage_root=_DATA_ROOT)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    game_info = game_service.get_game_info(_GAME_ID)
    case = DiscoveredCase(
        id=f"{_GAME_ID}-p1-host{_HOST_TURN}",
        game_id=_GAME_ID,
        perspective=1,
        host_turn=_HOST_TURN,
    )
    listing = _listing_for_case(
        case,
        store=StoreService(storage),
        turn_load=turn_load,
        game_info=game_info,
    )
    assert listing.player_id == _PLAYER_ID
    assert "Quantam Drive 7" in listing.summary
    assert "Plasma Bolt" in listing.summary


@pytest.mark.skipif(
    not (_DATA_ROOT / "games" / str(_GAME_ID) / "1" / "turns" / "3.json").is_file(),
    reason="local game 673864 store only",
)
def test_run_discovered_case_resolves_ground_truth_from_player_perspective():
    from tests.inference_corpus.run import run_discovered_case

    storage = configure_file_storage(storage_root=_DATA_ROOT)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)
    case = DiscoveredCase(
        id=f"{_GAME_ID}-p1-host{_HOST_TURN}",
        game_id=_GAME_ID,
        perspective=1,
        host_turn=_HOST_TURN,
    )
    result = run_discovered_case(
        case,
        turn_load=turn_load,
        game_service=game_service,
        store=store,
        max_complexity="adjunct",
        include_adjunct=True,
    )
    assert result.ground_truth_available is True
