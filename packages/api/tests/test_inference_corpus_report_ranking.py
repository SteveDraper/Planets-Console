"""Unit tests for corpus report exit codes under hard ranking policy."""

from tests.inference_corpus.models import CaseOutcome, CorpusCaseResult, CorpusReport


def test_exit_code_zero_for_soft_ranking_miss():
    report = CorpusReport(
        results=[
            CorpusCaseResult(
                case_id="case-a",
                outcome=CaseOutcome.RANKING_MISS,
                hard_ranking_miss=False,
            )
        ]
    )
    assert report.exit_code == 0


def test_exit_code_one_for_hard_ranking_miss():
    report = CorpusReport(
        results=[
            CorpusCaseResult(
                case_id="case-a",
                outcome=CaseOutcome.RANKING_MISS,
                hard_ranking_miss=True,
            )
        ]
    )
    assert report.exit_code == 1


def test_case_result_json_includes_ranking_fields():
    from tests.inference_corpus.report import case_result_to_dict

    payload = case_result_to_dict(
        CorpusCaseResult(
            case_id="case-a",
            outcome=CaseOutcome.RANKING_MISS,
            ground_truth_rank=4,
            top_k=3,
            failure_message="ground truth not in top 3",
        )
    )
    assert payload["outcome"] == "ranking_miss"
    assert payload["groundTruthRank"] == 4
    assert payload["topK"] == 3
    assert payload["failureMessage"] == "ground truth not in top 3"
