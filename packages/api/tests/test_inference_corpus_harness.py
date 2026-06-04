"""Unit tests for inference corpus harness helpers."""

import pytest

from tests.inference_corpus.manifest import load_manifest, resolve_player_id
from tests.inference_corpus.models import COMPLEXITY_ORDINAL, CaseOutcome
from tests.inference_corpus.run import run_manifest_case


def test_load_fixed_manifest_has_seed_cases():
    _, cases = load_manifest()
    assert len(cases) == 2
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    assert host2.host_turn == 2
    assert host2.complexity == "minimal"
    assert host2.expected_status == "exact"
    assert host2.expect_coverage is False
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
