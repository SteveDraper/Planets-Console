"""Tier 1 inference run for one loaded corpus case."""

import time
from dataclasses import dataclass, replace

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import run_inference_with_artifacts
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_TIME_LIMITED
from api.models.game import TurnInfo
from api.models.player import Score

from tests.inference_corpus.models import CaseOutcome, ComplexityLevel, CorpusCaseResult
from tests.inference_corpus.verify import verify_top_solution_hard_equalities


@dataclass(frozen=True)
class Tier1RunResult:
    result: CorpusCaseResult
    inference_payload: dict[str, object] | None


def _tier1_run_result(
    *,
    case_id: str,
    outcome: CaseOutcome,
    elapsed_seconds: float,
    inference_payload: dict[str, object] | None = None,
    failure_message: str | None = None,
    status: str | None = None,
    solution_count: int | None = None,
    complexity: ComplexityLevel | None = None,
    complexity_reasons: tuple[str, ...] = (),
    ground_truth_available: bool | None = None,
) -> Tier1RunResult:
    return Tier1RunResult(
        result=replace(
            CorpusCaseResult(
                case_id=case_id,
                outcome=outcome,
                failure_message=failure_message,
                status=status,
                solution_count=solution_count,
                complexity=complexity,
                complexity_reasons=complexity_reasons,
                ground_truth_available=ground_truth_available,
            ),
            elapsed_seconds=elapsed_seconds,
        ),
        inference_payload=inference_payload,
    )


def _run_tier1_for_loaded_case(
    *,
    case_id: str,
    score_turn: TurnInfo,
    score: Score,
    complexity: ComplexityLevel | None,
    complexity_reasons: tuple[str, ...],
    expected_status: str,
    ground_truth_available: bool | None = None,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    load_scoreboard_turn=None,
    case_time_limit_seconds: float | None = None,
) -> Tier1RunResult:
    started_at = time.monotonic()
    inference, inference_observation, solve_catalog = run_inference_with_artifacts(
        score,
        score_turn,
        load_scoreboard_turn=load_scoreboard_turn,
        time_limit_seconds=case_time_limit_seconds,
    )
    elapsed_seconds = time.monotonic() - started_at

    common_fields = {
        "case_id": case_id,
        "complexity": complexity,
        "complexity_reasons": complexity_reasons,
        "ground_truth_available": ground_truth_available,
        "elapsed_seconds": elapsed_seconds,
    }

    status = inference.get("status")
    if not isinstance(status, str):
        return _tier1_run_result(
            outcome=CaseOutcome.FAILED,
            failure_message="inference payload missing status",
            **common_fields,
        )

    solution_count_raw = inference.get("solutionCount", 0)
    solution_count = solution_count_raw if isinstance(solution_count_raw, int) else 0

    status_failure = _tier1_status_failure(
        expected_status=expected_status,
        complexity=complexity,
        status=status,
        solution_count=solution_count,
    )
    if status_failure is not None:
        return _tier1_run_result(
            outcome=CaseOutcome.FAILED,
            status=status,
            solution_count=solution_count,
            failure_message=status_failure,
            **common_fields,
        )

    if status in {STATUS_EXACT, STATUS_TIME_LIMITED} and solution_count >= 1:
        verify_failure = verify_top_solution_hard_equalities(
            observation=inference_observation,
            catalog=solve_catalog if solve_catalog is not None else catalog,
            inference_payload=inference,
        )
        if verify_failure is not None:
            return _tier1_run_result(
                outcome=CaseOutcome.FAILED,
                status=status,
                solution_count=solution_count,
                failure_message=verify_failure,
                **common_fields,
            )

    return _tier1_run_result(
        outcome=CaseOutcome.PASSED,
        status=status,
        solution_count=solution_count,
        inference_payload=inference,
        **common_fields,
    )


def _tier1_status_failure(
    *,
    expected_status: str,
    complexity: ComplexityLevel | None,
    status: str,
    solution_count: int,
) -> str | None:
    if status == expected_status:
        if expected_status == "exact" and solution_count < 1:
            return "expected at least one solution for exact status"
        return None

    if (
        complexity == "heavy"
        and expected_status == "exact"
        and status == STATUS_TIME_LIMITED
        and solution_count >= 1
    ):
        return None

    return f"status {status!r} != expected {expected_status!r} (solutions={solution_count})"
