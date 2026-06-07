"""Tests for sequential local corpus runs with inference-failure early stop."""

import time
from unittest.mock import MagicMock

from tests.inference_corpus.models import CaseOutcome, CorpusCaseResult, DiscoveredCase
from tests.inference_corpus.report import run_local_corpus
from tests.inference_corpus.worker import DiscoveredCaseJob


def _discovered_case(host_turn: int) -> DiscoveredCase:
    return DiscoveredCase(
        id=f"628580-p1-host{host_turn}",
        game_id=628580,
        perspective=1,
        host_turn=host_turn,
    )


def _result(case_id: str, outcome: CaseOutcome) -> CorpusCaseResult:
    return CorpusCaseResult(case_id=case_id, outcome=outcome)


def test_run_local_corpus_stops_after_inference_failure_budget(monkeypatch):
    cases = [_discovered_case(host_turn) for host_turn in (2, 3, 4, 5, 6)]
    outcomes = [
        CaseOutcome.PASSED,
        CaseOutcome.FAILED,
        CaseOutcome.SKIPPED_COMPLEXITY,
        CaseOutcome.OUT_OF_SEARCH_SPACE,
        CaseOutcome.PASSED,
    ]

    monkeypatch.setattr(
        "tests.inference_corpus.report.discover_cases",
        lambda *args, **kwargs: cases,
    )

    def fake_run_discovered_case(case, **kwargs):
        index = cases.index(case)
        return _result(case.id, outcomes[index])

    monkeypatch.setattr(
        "tests.inference_corpus.report.run_discovered_case",
        fake_run_discovered_case,
    )

    report = run_local_corpus(
        store=MagicMock(),
        turn_load=MagicMock(),
        game_service=MagicMock(),
        game_id=628580,
        stop_after_failures=2,
    )

    assert [result.case_id for result in report.results] == [
        "628580-p1-host2",
        "628580-p1-host3",
        "628580-p1-host4",
        "628580-p1-host5",
    ]
    assert report.inference_failure_count == 2
    assert report.stopped_early is True
    assert report.stop_reason == "inference_failure_budget_reached:2"


def test_run_local_corpus_stops_after_probe_time_limit(monkeypatch):
    cases = [_discovered_case(host_turn) for host_turn in (2, 3, 4, 5)]
    monkeypatch.setattr(
        "tests.inference_corpus.report.discover_cases",
        lambda *args, **kwargs: cases,
    )

    def fake_run_discovered_case(case, **kwargs):
        time.sleep(0.05)
        return _result(case.id, CaseOutcome.PASSED)

    monkeypatch.setattr(
        "tests.inference_corpus.report.run_discovered_case",
        fake_run_discovered_case,
    )

    report = run_local_corpus(
        store=MagicMock(),
        turn_load=MagicMock(),
        game_service=MagicMock(),
        game_id=628580,
        probe_time_limit_seconds=0.08,
    )

    assert len(report.results) < len(cases)
    assert report.stopped_early is True
    assert report.stop_reason == "probe_time_limit_reached:0.08"


def test_run_local_corpus_uses_process_pool_when_workers_gt_one(monkeypatch, tmp_path):
    cases = [_discovered_case(host_turn) for host_turn in (2, 3, 4, 5)]
    monkeypatch.setattr(
        "tests.inference_corpus.report.discover_cases",
        lambda *args, **kwargs: cases,
    )

    mapped_jobs: list[DiscoveredCaseJob] = []

    class FakePool:
        def __init__(self, max_workers: int) -> None:
            assert max_workers == 2

        def __enter__(self) -> FakePool:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def map(self, worker_fn, jobs: list[DiscoveredCaseJob]) -> list[CorpusCaseResult]:
            mapped_jobs.extend(jobs)
            return [_result(job.case.id, CaseOutcome.PASSED) for job in jobs]

    monkeypatch.setattr("tests.inference_corpus.report.ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(
        "tests.inference_corpus.report.per_process_search_workers",
        lambda workers: 2,
    )

    report = run_local_corpus(
        store=MagicMock(),
        turn_load=MagicMock(),
        game_service=MagicMock(),
        game_id=628580,
        workers=2,
        storage_root=tmp_path,
    )

    assert len(mapped_jobs) == len(cases)
    assert all(job.storage_root == str(tmp_path.resolve()) for job in mapped_jobs)
    assert all(job.num_search_workers == 2 for job in mapped_jobs)
    assert report.passed_count == len(cases)


def test_per_process_search_workers_scales_down_with_parallelism():
    from tests.inference_corpus.report import per_process_search_workers

    assert per_process_search_workers(1) is None
    assert per_process_search_workers(4) >= 1
