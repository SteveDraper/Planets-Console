"""Scores analytic integration for military score build inference."""

from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
    needs_accelerated_backfill,
    observation_deltas_from_score,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.constraints import (
    InferenceHardConstraints,
    observation_to_constraints_payload,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    prior_turn_score_data_available,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_target import (
    ScoreboardTurnLoader,
    is_after_ship_limit,
    load_accelerated_backfill_source_for_host_turn,
    observation_from_accelerated_segment,
    observation_from_deltas,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)
from api.models.game import TurnInfo
from api.models.player import Score

STATUS_NO_PRIOR_TURN = "no_prior_turn"
STATUS_SOLVER_ERROR = "solver_error"

__all__ = [
    "is_after_ship_limit",
    "prior_turn_score_data_available",
    "run_inference_with_artifacts",
]

AcceleratedSegmentArtifacts = tuple[InferenceObservation, ActionCatalog]


def _no_prior_turn_reason(turn: TurnInfo) -> str:
    if turn.settings.turn <= 1:
        return "first_turn"
    if needs_accelerated_backfill(turn.settings.turn, turn.settings):
        return "accelerated_backfill_unavailable"
    return "first_turn"


def build_inference_observation(score: Score, turn: TurnInfo) -> InferenceObservation:
    """Build solver observation for the reported host turn on this scoreboard row."""
    return observation_from_deltas(
        score,
        turn,
        observation_deltas_from_score(score, turn),
    )


def catalog_to_actions_payload(
    catalog: ActionCatalog,
    *,
    turn: TurnInfo | None = None,
    observation: InferenceObservation | None = None,
) -> dict[str, object]:
    """Serialize the bounded action catalog for diagnostics."""
    payload: dict[str, object] = {
        "catalogSize": catalog.catalog_size,
        "aggregateActionCount": len(catalog.aggregate_actions),
        "shipBuildComboCount": len(catalog.ship_build_combos),
        "policyStepId": catalog.policy_step_id,
        "policyStepIndex": catalog.policy_step_index,
        "actions": [
            {
                "id": action.id,
                "label": action.label,
                "scoreDelta2x": action.score_delta_2x,
                "warshipDelta": action.warship_delta,
                "freighterDelta": action.freighter_delta,
                "priorityPointDelta": action.priority_point_delta,
                "buildSlotUsage": action.build_slot_usage,
                "lowerBound": action.lower_bound,
                "upperBound": action.upper_bound,
                "probabilityWeight": action.probability_weight,
            }
            for action in catalog.aggregate_actions
        ],
        "shipBuildCombos": [
            {
                "comboId": combo.combo_id,
                "label": combo.labels[0],
                "hullId": combo.hull_id,
                "engineId": combo.engine_id,
                "beamId": combo.beam_id,
                "torpId": combo.torp_id,
                "beamCount": combo.beam_count,
                "launcherCount": combo.launcher_count,
                "upperBound": combo.upper_bound,
                "scoreDelta2x": combo.score_delta_2x,
            }
            for combo in catalog.ship_build_combos
        ],
    }
    if turn is not None and observation is not None:
        buildable_hull_ids = buildable_hull_ids_for_player(turn, observation.player_id)
        hulls_by_id = {hull.id: hull for hull in turn.hulls}
        buildable_starship_hull_ids = sorted(
            hull_id for hull_id in buildable_hull_ids if hull_id in hulls_by_id
        )
        payload["meta"] = {
            "buildableHullIds": sorted(buildable_hull_ids),
            "buildableStarshipHullIds": buildable_starship_hull_ids,
            "buildableHullIdsMissingFromCatalog": sorted(
                hull_id for hull_id in buildable_hull_ids if hull_id not in hulls_by_id
            ),
            "shipBuildComboIds": [combo.combo_id for combo in catalog.ship_build_combos],
        }
    return payload


def build_inference_solver_diagnostics(
    *,
    turn: int,
    observation: InferenceObservation | None = None,
    problem: InferenceProblem | None = None,
    catalog: ActionCatalog | None = None,
    turn_info: TurnInfo | None = None,
    solver: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Structured solver diagnostics for the diagnostics panel."""
    payload: dict[str, object] = {"turn": turn}
    if observation is not None:
        hard_constraints = (
            InferenceHardConstraints.from_problem(problem)
            if problem is not None
            else InferenceHardConstraints()
        )
        payload["constraints"] = observation_to_constraints_payload(
            observation,
            hard_constraints=hard_constraints,
            aggregate_action_ids=(
                frozenset(action.id for action in problem.aggregate_actions)
                if problem is not None
                else None
            ),
        )
    if catalog is not None:
        payload["actionCatalog"] = catalog_to_actions_payload(
            catalog,
            turn=turn_info,
            observation=observation,
        )
        payload.update(catalog.diagnostics())
    if solver is not None:
        payload["solver"] = solver
    if extra:
        payload.update(extra)
    return payload


def _no_prior_turn_inference_result(
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    return (
        _inference_api_payload(
            status=STATUS_NO_PRIOR_TURN,
            summary="Prior turn score data unavailable",
            solutions=(),
            diagnostics=build_inference_solver_diagnostics(
                turn=turn.settings.turn,
                observation=resolved_observation,
                turn_info=turn,
                extra={"reason": _no_prior_turn_reason(turn)},
            ),
        ),
        resolved_observation,
        None,
    )


def _run_accelerated_backfill_inference(
    score: Score,
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    backfill = _try_accelerated_backfill_inference(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if backfill is not None:
        return backfill
    return _no_prior_turn_inference_result(turn, resolved_observation)


def _run_accelerated_split_inference_path(
    score: Score,
    turn: TurnInfo,
    segments: tuple[AcceleratedInferenceSegment, ...],
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    payload, reported_observation, reported_catalog, _ = _run_accelerated_split_inference(
        score,
        turn,
        segments,
    )
    return payload, reported_observation, reported_catalog


def _run_policy_ladder_inference(
    resolved_observation: InferenceObservation,
    turn: TurnInfo,
) -> tuple[InferenceResult, ActionCatalog, InferenceProblem, list[str], list[dict[str, object]]]:
    return solve_with_policy_ladder(
        resolved_observation,
        turn,
    )


def _run_corpus_prebuilt_inference(
    resolved_observation: InferenceObservation,
    catalog: ActionCatalog,
) -> tuple[InferenceResult, ActionCatalog, InferenceProblem, list[str], list[dict[str, object]]]:
    problem = build_inference_problem(resolved_observation, catalog)
    result = solve_inference_problem(problem)
    return result, catalog, problem, [catalog.policy_step_id], []


def _solver_error_inference_result(
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
    solve_catalog: ActionCatalog | None,
    exc: Exception,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    return (
        _inference_api_payload(
            status=STATUS_SOLVER_ERROR,
            summary="Build inference failed",
            solutions=(),
            diagnostics=build_inference_solver_diagnostics(
                turn=turn.settings.turn,
                observation=resolved_observation,
                catalog=solve_catalog,
                turn_info=turn,
                extra={"error": str(exc)},
            ),
        ),
        resolved_observation,
        solve_catalog,
    )


def _run_solver_inference_path(
    path: InferencePath,
    score: Score,
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
    *,
    catalog: ActionCatalog | None,
    accelerated_segments: tuple[AcceleratedInferenceSegment, ...] | None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    if path == InferencePath.ACCELERATED_SPLIT:
        assert accelerated_segments is not None
        return _run_accelerated_split_inference_path(score, turn, accelerated_segments)

    solve_catalog = catalog
    try:
        if path == InferencePath.POLICY_LADDER:
            result, solve_catalog, problem, policy_steps_attempted, step_diagnostics = (
                _run_policy_ladder_inference(resolved_observation, turn)
            )
        else:
            assert path == InferencePath.CORPUS_PREBUILT
            assert solve_catalog is not None
            result, solve_catalog, problem, policy_steps_attempted, step_diagnostics = (
                _run_corpus_prebuilt_inference(resolved_observation, solve_catalog)
            )
        return (
            inference_result_to_api_payload(
                result,
                solve_catalog,
                resolved_observation,
                turn,
                problem,
                policy_steps_attempted=policy_steps_attempted,
                step_diagnostics=step_diagnostics,
            ),
            resolved_observation,
            solve_catalog,
        )
    except Exception as exc:
        return _solver_error_inference_result(turn, resolved_observation, solve_catalog, exc)


def run_inference_with_artifacts(
    score: Score,
    turn: TurnInfo,
    *,
    observation: InferenceObservation | None = None,
    catalog: ActionCatalog | None = None,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    """Run inference once; return API payload plus observation and catalog for re-checks.

    When ``observation`` and ``catalog`` are supplied (e.g. corpus harness), they are
    reused for solving and returned unchanged so constraint re-check uses the same
    catalog instance as coverage evaluation.
    """
    resolved_observation = (
        observation if observation is not None else build_inference_observation(score, turn)
    )
    path, accelerated_segments = resolve_inference_path(
        score,
        turn,
        catalog=catalog,
        load_scoreboard_turn=load_scoreboard_turn,
    )

    if path == InferencePath.NO_PRIOR_TURN:
        return _no_prior_turn_inference_result(turn, resolved_observation)
    if path == InferencePath.ACCELERATED_BACKFILL:
        return _run_accelerated_backfill_inference(
            score,
            turn,
            resolved_observation,
            load_scoreboard_turn=load_scoreboard_turn,
        )
    return _run_solver_inference_path(
        path,
        score,
        turn,
        resolved_observation,
        catalog=catalog,
        accelerated_segments=accelerated_segments,
    )


def _try_accelerated_backfill_inference(
    score: Score,
    turn: TurnInfo,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None] | None:
    """Fill unreliable accelerated rows from the first reliable split when that turn is stored."""
    if load_scoreboard_turn is None:
        return None

    target_host_turn = scoreboard_host_turn(turn.settings.turn)
    if target_host_turn is None:
        return None

    backfill_source = load_accelerated_backfill_source_for_host_turn(
        score,
        turn,
        host_turn=target_host_turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if backfill_source is None:
        return None

    payload, _, _, segment_artifacts = _run_accelerated_split_inference(
        backfill_source.source_score,
        backfill_source.source_turn,
        backfill_source.segments,
    )
    segment_payload = _segment_payload_for_host_turn(
        payload,
        host_turn=target_host_turn,
    )
    if segment_payload is None:
        return None

    artifacts = segment_artifacts.get(target_host_turn)
    if artifacts is None:
        return None
    segment_observation, segment_catalog = artifacts
    segment_status = segment_payload.get("status")
    if not isinstance(segment_status, str):
        return None

    solutions_raw = segment_payload.get("solutions")
    solution_count_raw = segment_payload.get("solutionCount", 0)
    solution_count = solution_count_raw if isinstance(solution_count_raw, int) else 0

    split_diagnostics = payload.get("diagnostics")
    accelerated_segments = (
        split_diagnostics.get("accelerated_segments")
        if isinstance(split_diagnostics, dict)
        else None
    )
    return (
        {
            "status": segment_status,
            "summary": _summary_from_segment_payload(segment_payload),
            "solutionCount": solution_count,
            "isComplete": segment_status != STATUS_TIME_LIMITED,
            "solutions": solutions_raw if isinstance(solutions_raw, list) else [],
            "diagnostics": build_inference_solver_diagnostics(
                turn=turn.settings.turn,
                observation=segment_observation,
                catalog=segment_catalog,
                turn_info=backfill_source.source_turn,
                extra={
                    "accelerated_backfill": True,
                    "accelerated_backfill_source_turn": backfill_source.source_turn_number,
                    "accelerated_backfill_host_turn": target_host_turn,
                    "accelerated_backfill_segment_id": segment_payload.get("segmentId"),
                    "accelerated_segments": accelerated_segments,
                },
            ),
        },
        segment_observation,
        segment_catalog,
    )


def _segment_payload_for_host_turn(
    split_payload: dict[str, object],
    *,
    host_turn: int,
) -> dict[str, object] | None:
    diagnostics = split_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    segments_raw = diagnostics.get("accelerated_segments")
    if not isinstance(segments_raw, list):
        return None
    for entry in segments_raw:
        if not isinstance(entry, dict):
            continue
        entry_host_turn = entry.get("hostTurn")
        if entry_host_turn == host_turn:
            return entry
    return None


def _summary_from_segment_payload(segment_payload: dict[str, object]) -> str:
    status = segment_payload.get("status")
    if status == STATUS_NO_EXACT_SOLUTION:
        return "No feasible build explanation found"
    if status == STATUS_INVALID_PROBLEM:
        return "Invalid inference problem"
    solutions_raw = segment_payload.get("solutions")
    if not isinstance(solutions_raw, list) or not solutions_raw:
        return "No feasible build explanation found"
    first = solutions_raw[0]
    if not isinstance(first, dict):
        return "No feasible build explanation found"
    parts: list[str] = []
    actions = first.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            label = action.get("label")
            count = action.get("count")
            if not isinstance(label, str) or not isinstance(count, int) or count <= 0:
                continue
            parts.append(label if count == 1 else f"{count}x {label}")
    ship_builds = first.get("shipBuilds")
    if isinstance(ship_builds, list):
        for build in ship_builds:
            if not isinstance(build, dict):
                continue
            label = build.get("label")
            count = build.get("count")
            if not isinstance(label, str) or not isinstance(count, int) or count <= 0:
                continue
            parts.append(label if count == 1 else f"{count}x {label}")
    if not parts:
        return "No feasible build explanation found"
    return f"Best: {'; '.join(parts)}"


def _run_accelerated_split_inference(
    score: Score,
    turn: TurnInfo,
    segments: tuple[AcceleratedInferenceSegment, ...],
) -> tuple[
    dict[str, object],
    InferenceObservation,
    ActionCatalog | None,
    dict[int, AcceleratedSegmentArtifacts],
]:
    """Solve accel-window and reported-host-turn targets independently."""
    segment_count = len(segments)
    per_segment_time = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS / segment_count
    per_segment_max_solutions = max(1, 20 // segment_count)

    segment_payloads: list[dict[str, object]] = []
    segment_artifacts: dict[int, AcceleratedSegmentArtifacts] = {}
    reported_observation: InferenceObservation | None = None
    reported_catalog: ActionCatalog | None = None
    reported_problem: InferenceProblem | None = None
    reported_result: InferenceResult | None = None
    reported_policy_steps: list[str] = []
    reported_step_diagnostics: list[dict[str, object]] = []
    combined_time_limited = False

    for segment in segments:
        segment_observation = observation_from_accelerated_segment(score, turn, segment)
        if segment.segment_id == "reported_host_turn":
            reported_observation = segment_observation

        result, catalog, problem, policy_steps_attempted, step_diagnostics = (
            solve_with_policy_ladder(
                segment_observation,
                turn,
                max_solutions=per_segment_max_solutions,
                time_limit_seconds=per_segment_time,
            )
        )
        segment_artifacts[segment.host_turn] = (segment_observation, catalog)
        if segment.segment_id == "reported_host_turn":
            reported_catalog = catalog
            reported_problem = problem
            reported_result = result
            reported_policy_steps = policy_steps_attempted
            reported_step_diagnostics = step_diagnostics
        if result.status == STATUS_TIME_LIMITED:
            combined_time_limited = True

        segment_payloads.append(
            {
                "segmentId": segment.segment_id,
                "hostTurn": segment.host_turn,
                "status": result.status,
                "solutionCount": len(result.solutions),
                "militaryDelta2x": segment.military_delta_2x,
                "warshipDelta": segment.warship_delta,
                "freighterDelta": segment.freighter_delta,
                "policyStepsAttempted": policy_steps_attempted,
                "policyStepAttempts": step_diagnostics,
                "solutions": [
                    _serialize_solution_with_arithmetic(segment_observation, catalog, solution)
                    for solution in result.solutions
                ],
            }
        )

    assert reported_observation is not None
    assert reported_catalog is not None
    assert reported_problem is not None
    assert reported_result is not None

    overall_status = _accelerated_split_status(segment_payloads, combined_time_limited)
    primary_result = InferenceResult(
        status=overall_status,
        solutions=reported_result.solutions,
        diagnostics={
            **reported_result.diagnostics,
            "accelerated_segments": segment_payloads,
        },
    )

    return (
        inference_result_to_api_payload(
            primary_result,
            reported_catalog,
            reported_observation,
            turn,
            reported_problem,
            policy_steps_attempted=reported_policy_steps,
            step_diagnostics=reported_step_diagnostics,
            extra_diagnostics={"accelerated_segments": segment_payloads},
        ),
        reported_observation,
        reported_catalog,
        segment_artifacts,
    )


def _accelerated_split_status(
    segment_payloads: list[dict[str, object]],
    combined_time_limited: bool,
) -> str:
    statuses = [
        payload["status"] for payload in segment_payloads if isinstance(payload["status"], str)
    ]
    if any(status == STATUS_NO_EXACT_SOLUTION for status in statuses):
        return STATUS_NO_EXACT_SOLUTION
    if any(status == STATUS_INVALID_PROBLEM for status in statuses):
        return STATUS_INVALID_PROBLEM
    if combined_time_limited or any(status == STATUS_TIME_LIMITED for status in statuses):
        return STATUS_TIME_LIMITED
    return STATUS_EXACT


def infer_military_score_build(score: Score, turn: TurnInfo) -> dict[str, object]:
    """Run build inference for one scoreboard row, isolating failures to that row."""
    payload, _, _ = run_inference_with_artifacts(score, turn)
    return payload


def inference_result_to_api_payload(
    result: InferenceResult,
    catalog: ActionCatalog,
    observation: InferenceObservation,
    turn: TurnInfo,
    problem: InferenceProblem,
    *,
    policy_steps_attempted: list[str] | None = None,
    step_diagnostics: list[dict[str, object]] | None = None,
    extra_diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    """Shape a solver result into the Core scores row inference object."""
    solver_diagnostics = {
        "status": result.status,
        **result.diagnostics,
    }
    diagnostics = build_inference_solver_diagnostics(
        turn=turn.settings.turn,
        observation=observation,
        problem=problem,
        catalog=catalog,
        turn_info=turn,
        solver=solver_diagnostics,
        extra={
            "policy_steps_attempted": policy_steps_attempted or [catalog.policy_step_id],
            "policy_step_attempts": step_diagnostics or [],
            **(extra_diagnostics or {}),
        },
    )
    return _inference_api_payload(
        status=result.status,
        summary=format_inference_summary(result),
        solutions=result.solutions,
        diagnostics=diagnostics,
        observation=observation,
        catalog=catalog,
    )


def format_inference_summary(result: InferenceResult) -> str:
    """Return compact row-level summary text for the inference column."""
    if result.status == STATUS_NO_PRIOR_TURN:
        return "Prior turn score data unavailable"
    if result.status == STATUS_INVALID_PROBLEM:
        reason = result.diagnostics.get("reason")
        if isinstance(reason, str) and reason:
            return f"Invalid inference problem: {reason}"
        return "Invalid inference problem"
    if result.status == STATUS_NO_EXACT_SOLUTION:
        return "No feasible build explanation found"
    if result.status == STATUS_SOLVER_ERROR:
        return "Build inference failed"
    if result.status == STATUS_TIME_LIMITED and not result.solutions:
        return "Inference timed out before finding a solution"
    if not result.solutions:
        return "No feasible build explanation found"

    best_summary = _format_solution_brief(result.solutions[0])
    alternative_count = len(result.solutions) - 1
    if alternative_count == 0:
        return f"Best: {best_summary}"
    if alternative_count == 1:
        return f"Best: {best_summary}; 1 alternative"
    return f"Best: {best_summary}; {alternative_count} alternatives"


def _format_solution_brief(solution: InferenceSolution) -> str:
    parts: list[str] = []
    for action in solution.actions:
        if action.count == 1:
            parts.append(action.label)
        else:
            parts.append(f"{action.count}x {action.label}")
    for ship_build in solution.ship_builds:
        if ship_build.count == 1:
            parts.append(ship_build.label)
        else:
            parts.append(f"{ship_build.count}x {ship_build.label}")
    return "; ".join(parts) if parts else "no actions"


def _inference_api_payload(
    *,
    status: str,
    summary: str,
    solutions: tuple[InferenceSolution, ...],
    diagnostics: dict[str, object],
    observation: InferenceObservation | None = None,
    catalog: ActionCatalog | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "summary": summary,
        "solutionCount": len(solutions),
        "isComplete": status != STATUS_TIME_LIMITED,
        "solutions": (
            [
                _serialize_solution_with_arithmetic(observation, catalog, solution)
                for solution in solutions
            ]
            if observation is not None and catalog is not None
            else [_serialize_solution_without_arithmetic(solution) for solution in solutions]
        ),
        "diagnostics": diagnostics,
    }


def _serialize_solution_actions(
    solution: InferenceSolution,
) -> list[dict[str, object]]:
    return [
        {
            "actionId": action.action_id,
            "label": action.label,
            "count": action.count,
        }
        for action in solution.actions
    ]


def _serialize_solution_ship_builds(
    solution: InferenceSolution,
) -> list[dict[str, object]]:
    return [
        {
            "comboId": ship_build.combo_id,
            "label": ship_build.label,
            "count": ship_build.count,
            "hullId": ship_build.hull_id,
            "engineId": ship_build.engine_id,
            "beamId": ship_build.beam_id,
            "torpId": ship_build.torp_id,
            "beamCount": ship_build.beam_count,
            "launcherCount": ship_build.launcher_count,
        }
        for ship_build in solution.ship_builds
    ]


def _serialize_solution_core(solution: InferenceSolution) -> dict[str, object]:
    return {
        "objectiveValue": solution.objective_value,
        "actions": _serialize_solution_actions(solution),
        "shipBuilds": _serialize_solution_ship_builds(solution),
    }


def _serialize_solution_with_arithmetic(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    solution: InferenceSolution,
) -> dict[str, object]:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    payload = _serialize_solution_core(solution)
    payload["militaryScoreArithmetic"] = solution_military_score_arithmetic_payload(
        solution,
        observation,
        actions_by_id,
        combos_by_id,
    )
    return payload


def _serialize_solution_without_arithmetic(solution: InferenceSolution) -> dict[str, object]:
    return _serialize_solution_core(solution)
