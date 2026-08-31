"""CI entry: fixed inference corpus manifest under tests/fixtures/inference_corpus/."""

from unittest.mock import patch

from tests.inference_corpus import run_fixed_corpus
from tests.inference_corpus.manifest import load_manifest
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.run import run_manifest_case


def test_fixed_inference_corpus_tier1_passes():
    report = run_fixed_corpus()
    assert report.failed_count == 0, "\n".join(report.summary_lines())
    assert report.hard_ranking_misses == []
    passed = [result for result in report.results if result.outcome == CaseOutcome.PASSED]
    skipped = [
        result for result in report.results if result.outcome == CaseOutcome.SKIPPED_COMPLEXITY
    ]
    assert len(passed) == 3
    assert len(skipped) == 1
    assert skipped[0].case_id == "628580-p6-host20"
    assert skipped[0].skip_reason == "adjunct_disabled"
    assert skipped[0].complexity == "adjunct"
    assert len(report.results) == 4


def test_fixed_corpus_host2_hard_ranking_lock_passes():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    assert host2.require_top_k is True
    result = run_manifest_case(host2)
    assert result.outcome == CaseOutcome.PASSED
    assert result.hard_ranking_miss is False


def test_hard_ranking_miss_fails_fixed_corpus_exit_code():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")

    wrong_gt_solution = {
        "status": "exact",
        "solutionCount": 2,
        "solutions": [
            {
                "actions": [],
                "shipBuilds": [{"comboId": "combo_99_1_none_none_0_0", "count": 1}],
            },
            {
                "actions": [],
                "shipBuilds": [{"comboId": "combo_13_9_3_6_8_6", "count": 1}],
            },
        ],
    }

    with (
        patch(
            "tests.inference_corpus.pipeline_tier1.run_inference_with_artifacts",
            return_value=(wrong_gt_solution, None, None),
        ),
        patch(
            "tests.inference_corpus.pipeline_tier1.verify_top_solution_hard_equalities",
            return_value=None,
        ),
    ):
        result = run_manifest_case(host2, top_k=1)

    assert result.outcome == CaseOutcome.RANKING_MISS
    assert result.hard_ranking_miss is True
    assert result.ground_truth_rank == 2
    assert result.top_k == 1

    from tests.inference_corpus.models import CorpusReport

    report = CorpusReport(results=[result])
    assert report.exit_code == 1


def test_fixed_corpus_coverage_case_has_ground_truth_available():
    report = run_fixed_corpus()
    coverage_case = next(
        result for result in report.results if result.case_id == "628580-p1-host51"
    )
    assert coverage_case.ground_truth_available is True


def test_fixed_inference_corpus_report_distinguishes_skip_buckets():
    """Harness exposes skip outcome enums; default CI uses skipped_complexity for adjunct."""
    assert CaseOutcome.SKIPPED_COMPLEXITY.value == "skipped_complexity"
    assert CaseOutcome.OUT_OF_SEARCH_SPACE.value == "out_of_search_space"


def test_fixed_adjunct_row_skipped_by_default():
    _, cases = load_manifest()
    adjunct = next(case for case in cases if case.id == "628580-p6-host20")
    skipped = run_manifest_case(adjunct)
    assert skipped.outcome == CaseOutcome.SKIPPED_COMPLEXITY
    assert skipped.skip_reason == "adjunct_disabled"
    assert skipped.complexity == "adjunct"


def test_included_adjunct_row_classifies_trade_hint_from_merged_perspective():
    _, cases = load_manifest()
    adjunct = next(case for case in cases if case.id == "628580-p6-host20")
    stub_payload = {
        "status": "exact",
        "solutionCount": 1,
        "solutions": [{"actions": [], "shipBuilds": []}],
    }
    with (
        patch(
            "tests.inference_corpus.pipeline_tier1.run_inference_with_artifacts",
            return_value=(stub_payload, None, None),
        ),
        patch(
            "tests.inference_corpus.pipeline_tier1.verify_top_solution_hard_equalities",
            return_value=None,
        ),
    ):
        result = run_manifest_case(adjunct, include_adjunct=True)
    assert result.complexity == "adjunct"
    assert "trade_or_capture_hint" in result.complexity_reasons
    assert result.coverage_reason != "deferred_trade"
    assert result.outcome != CaseOutcome.OUT_OF_SEARCH_SPACE
    assert result.ground_truth_available is False
