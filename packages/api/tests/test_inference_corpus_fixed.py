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
    assert report.passed_count == len(report.results)
    assert len(report.results) == 3
    for result in report.results:
        assert result.outcome == CaseOutcome.PASSED, (
            f"{result.case_id}: {result.outcome} ({result.failure_message or result.skip_reason})"
        )


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
    """Harness exposes skip outcome enums even when the fixed corpus does not use them yet."""
    assert CaseOutcome.SKIPPED_COMPLEXITY.value == "skipped_complexity"
    assert CaseOutcome.OUT_OF_SEARCH_SPACE.value == "out_of_search_space"
