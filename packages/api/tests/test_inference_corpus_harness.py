"""Unit tests for inference corpus harness helpers."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from api.concepts.races import HORWASP_RACE_ID

from tests.inference_corpus.fixtures import load_turn_fixture
from tests.inference_corpus.manifest import load_manifest, resolve_player_id
from tests.inference_corpus.models import (
    COMPLEXITY_ORDINAL,
    INFERENCE_FAILURE_OUTCOMES,
    CaseOutcome,
    DiscoveredCase,
)
from tests.inference_corpus.run import HORWASP_SKIP_REASON, run_discovered_case, run_manifest_case


def test_load_fixed_manifest_has_seed_cases():
    _, cases = load_manifest()
    assert len(cases) == 3
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    assert host2.host_turn == 2
    assert host2.complexity == "minimal"
    assert host2.expected_status == "exact"
    assert host2.expect_coverage is False
    assert host2.require_top_k is True
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    assert host51.expect_coverage is True


def test_resolve_player_id_from_game_info():
    _, cases = load_manifest()
    assert resolve_player_id(cases[0]) == 1


def test_adjunct_case_skipped_by_default():
    _, cases = load_manifest()
    case = cases[0]
    adjunct_case = case.__class__(
        **{**case.__dict__, "id": "adjunct-stub", "complexity": "adjunct"}
    )
    result = run_manifest_case(adjunct_case)
    assert result.outcome == CaseOutcome.SKIPPED_COMPLEXITY
    assert result.skip_reason == "adjunct_disabled"


def test_horwasp_manifest_case_skipped_without_inference_failure():
    _, cases = load_manifest()
    case = cases[0]
    prior_turn = load_turn_fixture(case.prior_turn_path)
    score_turn = load_turn_fixture(case.score_turn_path)
    horwasp_player = replace(prior_turn.player, raceid=HORWASP_RACE_ID)
    prior_turn = replace(prior_turn, player=horwasp_player)
    score_turn = replace(score_turn, player=horwasp_player)
    horwasp_case = case.__class__(**{**case.__dict__, "id": "horwasp-stub"})

    with (
        patch(
            "tests.inference_corpus.run.load_turn_fixture",
            side_effect=[prior_turn, score_turn],
        ),
        patch(
            "tests.inference_corpus.run.load_manifest_ground_truth_turn_snapshots",
            return_value=(prior_turn, score_turn),
        ),
    ):
        result = run_manifest_case(horwasp_case)

    assert result.outcome == CaseOutcome.SKIPPED_UNSUPPORTED_RACE
    assert result.skip_reason == HORWASP_SKIP_REASON
    assert result.outcome not in INFERENCE_FAILURE_OUTCOMES


def test_horwasp_discovered_case_skipped_without_inference_failure():
    case = DiscoveredCase(
        id="999-p1-host2",
        game_id=999,
        perspective=1,
        host_turn=2,
    )
    prior_turn = load_turn_fixture("628580/1/turns/2.json")
    score_turn = load_turn_fixture("628580/1/turns/3.json")
    horwasp_player = replace(prior_turn.player, raceid=HORWASP_RACE_ID)
    prior_turn = replace(prior_turn, player=horwasp_player)
    score_turn = replace(score_turn, player=horwasp_player)

    turn_load = MagicMock()
    turn_load.get_turn_info.side_effect = lambda _gid, _perspective, turn_number: (
        prior_turn if turn_number == 2 else score_turn
    )
    game_service = MagicMock()
    store = MagicMock()

    with (
        patch(
            "tests.inference_corpus.run.resolve_player_id_for_case",
            return_value=prior_turn.player.id,
        ),
        patch(
            "tests.inference_corpus.run.merged_inventory_for_case",
            return_value=MagicMock(),
        ),
        patch(
            "tests.inference_corpus.run.score_for_player",
            return_value=score_turn.scores[0],
        ),
        patch(
            "tests.inference_corpus.run.classify_complexity",
            return_value=("minimal", ()),
        ),
    ):
        result = run_discovered_case(
            case,
            turn_load=turn_load,
            game_service=game_service,
            store=store,
        )

    assert result.outcome == CaseOutcome.SKIPPED_UNSUPPORTED_RACE
    assert result.skip_reason == HORWASP_SKIP_REASON
    assert result.outcome not in INFERENCE_FAILURE_OUTCOMES


def test_complexity_ordinal_ordering():
    assert COMPLEXITY_ORDINAL["minimal"] < COMPLEXITY_ORDINAL["adjunct"]


def test_manifest_rejects_empty_cases(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"version": 1, "cases": []}')
    with pytest.raises(ValueError, match="non-empty"):
        load_manifest(manifest_path)


def test_manifest_rejects_non_integer_required_perspectives(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        """
        {
          "version": 1,
          "cases": [{
            "id": "bad-required",
            "gameId": 1,
            "perspective": 1,
            "hostTurn": 2,
            "priorTurnPath": "a/1/turns/2.json",
            "scoreTurnPath": "a/1/turns/3.json",
            "requiredPerspectives": [1, "2"]
          }]
        }
        """
    )
    with pytest.raises(ValueError, match=r"requiredPerspectives\[1\] must be an integer"):
        load_manifest(manifest_path)
