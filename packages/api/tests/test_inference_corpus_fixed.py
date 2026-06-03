"""CI entry: fixed inference corpus manifest under tests/fixtures/inference_corpus/."""

from tests.inference_corpus import run_fixed_corpus
from tests.inference_corpus.models import CaseOutcome


def test_fixed_inference_corpus_tier1_passes():
    report = run_fixed_corpus()
    assert report.failed_count == 0, "\n".join(report.summary_lines())
    assert report.passed_count == len(report.results)
    for result in report.results:
        assert result.outcome == CaseOutcome.PASSED, (
            f"{result.case_id}: {result.outcome} ({result.failure_message or result.skip_reason})"
        )


def test_fixed_inference_corpus_report_distinguishes_skip_buckets():
    """Harness exposes skip outcome enums even when the fixed corpus does not use them yet."""
    assert CaseOutcome.SKIPPED_COMPLEXITY.value == "skipped_complexity"
    assert CaseOutcome.OUT_OF_SEARCH_SPACE.value == "out_of_search_space"
