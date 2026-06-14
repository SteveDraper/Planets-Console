"""Aggregate inference corpus case results into a structured report."""

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.discovery import discover_cases
from tests.inference_corpus.manifest import DEFAULT_MANIFEST_PATH, load_manifest
from tests.inference_corpus.models import (
    INFERENCE_FAILURE_OUTCOMES,
    CaseOutcome,
    ComplexityLevel,
    CorpusCaseResult,
    CorpusReport,
    DiscoveredCase,
)
from tests.inference_corpus.run import run_discovered_case, run_manifest_case
from tests.inference_corpus.worker import DiscoveredCaseJob, run_discovered_case_job


def run_fixed_corpus(
    *,
    manifest_path: Path | None = None,
    max_complexity: ComplexityLevel = "heavy",
    include_adjunct: bool = False,
    top_k: int = 3,
    fail_on_ranking_miss: bool = False,
) -> CorpusReport:
    """Run every case listed in the fixed corpus manifest."""
    _, cases = load_manifest(manifest_path or DEFAULT_MANIFEST_PATH)
    report = CorpusReport()
    for case in cases:
        report.results.append(
            run_manifest_case(
                case,
                max_complexity=max_complexity,
                include_adjunct=include_adjunct,
                top_k=top_k,
                fail_on_ranking_miss=fail_on_ranking_miss,
            )
        )
    return report


def per_process_search_workers(workers: int) -> int | None:
    """Cap CP-SAT threads per worker so parallel probe runs do not oversubscribe CPU."""
    if workers <= 1:
        return None
    cpu_count = os.process_cpu_count() or workers
    return max(1, min(8, cpu_count // workers))


def run_local_corpus(
    *,
    store: StoreService,
    turn_load: TurnLoadService,
    game_service: GameService,
    game_id: int | None = None,
    min_host_turn: int | None = None,
    max_host_turn: int | None = None,
    max_complexity: ComplexityLevel = "heavy",
    include_adjunct: bool = False,
    stop_after_failures: int | None = None,
    probe_time_limit_seconds: float | None = None,
    workers: int = 1,
    storage_root: Path | None = None,
    top_k: int = 3,
    enable_tier2: bool = False,
    fail_on_ranking_miss: bool = False,
) -> CorpusReport:
    """Discover and run inference corpus cases from the file storage backend."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers > 1 and storage_root is None:
        raise ValueError("storage_root is required when workers > 1")

    cases = list(
        discover_cases(
            store,
            game_id=game_id,
            min_host_turn=min_host_turn,
            max_host_turn=max_host_turn,
        )
    )
    report = CorpusReport()
    started_at = time.monotonic()

    if workers == 1:
        _run_cases_sequential(
            cases,
            report=report,
            started_at=started_at,
            turn_load=turn_load,
            game_service=game_service,
            store=store,
            max_complexity=max_complexity,
            include_adjunct=include_adjunct,
            stop_after_failures=stop_after_failures,
            probe_time_limit_seconds=probe_time_limit_seconds,
            top_k=top_k,
            enable_tier2=enable_tier2,
            fail_on_ranking_miss=fail_on_ranking_miss,
        )
        return report

    resolved_storage_root = str(storage_root.resolve())
    search_workers = per_process_search_workers(workers)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        _run_cases_in_process_pool(
            cases,
            report=report,
            started_at=started_at,
            pool=pool,
            storage_root=resolved_storage_root,
            max_complexity=max_complexity,
            include_adjunct=include_adjunct,
            stop_after_failures=stop_after_failures,
            probe_time_limit_seconds=probe_time_limit_seconds,
            workers=workers,
            num_search_workers=search_workers,
            top_k=top_k,
            enable_tier2=enable_tier2,
            fail_on_ranking_miss=fail_on_ranking_miss,
        )
    return report


def _probe_time_limit_reached(
    started_at: float,
    probe_time_limit_seconds: float | None,
) -> bool:
    if probe_time_limit_seconds is None:
        return False
    return time.monotonic() - started_at >= probe_time_limit_seconds


def _mark_probe_time_limit_reached(
    report: CorpusReport,
    probe_time_limit_seconds: float,
) -> None:
    report.stopped_early = True
    report.stop_reason = f"probe_time_limit_reached:{probe_time_limit_seconds:g}"


def _mark_inference_failure_budget_reached(
    report: CorpusReport,
    stop_after_failures: int,
) -> None:
    report.stopped_early = True
    report.stop_reason = f"inference_failure_budget_reached:{stop_after_failures}"


def _should_stop_after_failures(
    results: list[CorpusCaseResult],
    stop_after_failures: int | None,
) -> bool:
    return stop_after_failures is not None and _inference_failure_count(results) >= (
        stop_after_failures
    )


def _run_cases_sequential(
    cases: list[DiscoveredCase],
    *,
    report: CorpusReport,
    started_at: float,
    turn_load: TurnLoadService,
    game_service: GameService,
    store: StoreService,
    max_complexity: ComplexityLevel,
    include_adjunct: bool,
    stop_after_failures: int | None,
    probe_time_limit_seconds: float | None,
    top_k: int,
    enable_tier2: bool,
    fail_on_ranking_miss: bool,
) -> None:
    for case in cases:
        if _probe_time_limit_reached(started_at, probe_time_limit_seconds):
            _mark_probe_time_limit_reached(report, probe_time_limit_seconds)
            break

        report.results.append(
            run_discovered_case(
                case,
                turn_load=turn_load,
                game_service=game_service,
                store=store,
                max_complexity=max_complexity,
                include_adjunct=include_adjunct,
                top_k=top_k,
                enable_tier2=enable_tier2,
                fail_on_ranking_miss=fail_on_ranking_miss,
            )
        )
        if _should_stop_after_failures(report.results, stop_after_failures):
            _mark_inference_failure_budget_reached(report, stop_after_failures)
            break


def _run_cases_in_process_pool(
    cases: list[DiscoveredCase],
    *,
    report: CorpusReport,
    started_at: float,
    pool: ProcessPoolExecutor,
    storage_root: str,
    max_complexity: ComplexityLevel,
    include_adjunct: bool,
    stop_after_failures: int | None,
    probe_time_limit_seconds: float | None,
    workers: int,
    num_search_workers: int | None,
    top_k: int,
    enable_tier2: bool,
    fail_on_ranking_miss: bool,
) -> None:
    index = 0
    while index < len(cases):
        if _probe_time_limit_reached(started_at, probe_time_limit_seconds):
            _mark_probe_time_limit_reached(report, probe_time_limit_seconds)
            break

        batch = cases[index : index + workers]
        jobs = [
            DiscoveredCaseJob(
                case=case,
                storage_root=storage_root,
                max_complexity=max_complexity,
                include_adjunct=include_adjunct,
                num_search_workers=num_search_workers,
                top_k=top_k,
                enable_tier2=enable_tier2,
                fail_on_ranking_miss=fail_on_ranking_miss,
            )
            for case in batch
        ]
        report.results.extend(pool.map(run_discovered_case_job, jobs))
        index += len(batch)

        if _should_stop_after_failures(report.results, stop_after_failures):
            _mark_inference_failure_budget_reached(report, stop_after_failures)
            break


def _inference_failure_count(results: list[CorpusCaseResult]) -> int:
    return sum(1 for result in results if result.outcome in INFERENCE_FAILURE_OUTCOMES)


def case_result_to_dict(result: CorpusCaseResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "caseId": result.case_id,
        "outcome": result.outcome.value,
    }
    if result.status is not None:
        payload["status"] = result.status
    if result.solution_count is not None:
        payload["solutionCount"] = result.solution_count
    if result.complexity is not None:
        payload["complexity"] = result.complexity
    if result.complexity_reasons:
        payload["complexityReasons"] = list(result.complexity_reasons)
    if result.ground_truth_available is not None:
        payload["groundTruthAvailable"] = result.ground_truth_available
    if result.coverage_reason is not None:
        payload["coverageReason"] = result.coverage_reason
    if result.skip_reason is not None:
        payload["skipReason"] = result.skip_reason
    if result.failure_message is not None:
        payload["failureMessage"] = result.failure_message
    if result.outcome == CaseOutcome.RANKING_MISS:
        payload["groundTruthRank"] = result.ground_truth_rank
        if result.top_k is not None:
            payload["topK"] = result.top_k
    elif result.ground_truth_rank is not None:
        payload["groundTruthRank"] = result.ground_truth_rank
    elif result.top_k is not None:
        payload["topK"] = result.top_k
    return payload


def report_to_json(report: CorpusReport) -> str:
    return json.dumps([case_result_to_dict(result) for result in report.results], indent=2)
