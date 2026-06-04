"""Aggregate inference corpus case results into a structured report."""

import json
from pathlib import Path

from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.discovery import discover_cases
from tests.inference_corpus.manifest import DEFAULT_MANIFEST_PATH, load_manifest
from tests.inference_corpus.models import (
    ComplexityLevel,
    CorpusCaseResult,
    CorpusReport,
)
from tests.inference_corpus.run import run_discovered_case, run_manifest_case


def run_fixed_corpus(
    *,
    manifest_path: Path | None = None,
    max_complexity: ComplexityLevel = "heavy",
    include_adjunct: bool = False,
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
            )
        )
    return report


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
) -> CorpusReport:
    """Discover and run inference corpus cases from the file storage backend."""
    report = CorpusReport()
    for case in discover_cases(
        store,
        game_id=game_id,
        min_host_turn=min_host_turn,
        max_host_turn=max_host_turn,
    ):
        report.results.append(
            run_discovered_case(
                case,
                turn_load=turn_load,
                game_service=game_service,
                store=store,
                max_complexity=max_complexity,
                include_adjunct=include_adjunct,
            )
        )
    return report


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
    return payload


def report_to_json(report: CorpusReport) -> str:
    return json.dumps([case_result_to_dict(result) for result in report.results], indent=2)
