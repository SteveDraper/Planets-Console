"""Scores analytic integration for military score build inference."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.analytics.military_score_inference.accelerated_start import (
    SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    AcceleratedInferenceSegment,
    accelerated_inference_segments,
    accelerated_turn_count,
    first_reliable_accelerated_scoreboard_turn,
    needs_accelerated_backfill,
    observation_deltas_from_score,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.constraints import (
    InferenceHardConstraints,
    observation_to_constraints_payload,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solution_signature,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_tier_policies,
)
from api.models.game import TurnInfo
from api.models.player import Score

STATUS_NO_PRIOR_TURN = "no_prior_turn"
STATUS_SOLVER_ERROR = "solver_error"

ScoreboardTurnLoader = Callable[[int], TurnInfo | None]

AcceleratedSegmentArtifacts = tuple[InferenceObservation, ActionCatalog]


@dataclass(frozen=True)
class ResolvedInferenceTarget:
    """Observation and turn snapshot used to build the action catalog for one host turn."""

    observation: InferenceObservation
    turn_info: TurnInfo
    score: Score


def resolve_inference_target_for_host_turn(
    score: Score,
    turn: TurnInfo,
    *,
    host_turn: int,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> ResolvedInferenceTarget | None:
    """Resolve catalog context for a host-turn target using inference-equivalent rules.

    Unreliable accelerated scoreboard rows backfill from the first reliable split;
    the first reliable row uses accelerated segments; later rows use score deltas.
    Returns None when accelerated context is required but cannot be loaded.
    """
    if needs_accelerated_backfill(turn.settings.turn, turn.settings):
        return _resolve_backfill_inference_target(
            score,
            turn,
            host_turn=host_turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )

    segments = accelerated_inference_segments(score, turn)
    if segments is not None:
        segment = _accelerated_segment_for_host_turn(segments, host_turn)
        if segment is None:
            return None
        return ResolvedInferenceTarget(
            observation=_observation_from_accelerated_segment(score, turn, segment),
            turn_info=turn,
            score=score,
        )

    expected_host_turn = scoreboard_host_turn(turn.settings.turn)
    if expected_host_turn is None or expected_host_turn != host_turn:
        return None
    return ResolvedInferenceTarget(
        observation=build_inference_observation(score, turn),
        turn_info=turn,
        score=score,
    )


def _resolve_backfill_inference_target(
    score: Score,
    turn: TurnInfo,
    *,
    host_turn: int,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> ResolvedInferenceTarget | None:
    if load_scoreboard_turn is None:
        return None

    scoreboard_turn_host = scoreboard_host_turn(turn.settings.turn)
    if scoreboard_turn_host is None or scoreboard_turn_host != host_turn:
        return None

    source_turn_number = first_reliable_accelerated_scoreboard_turn(turn.settings)
    if source_turn_number is None:
        return None

    source_turn = load_scoreboard_turn(source_turn_number)
    if source_turn is None:
        return None

    source_score = next(
        (row for row in source_turn.scores if row.ownerid == score.ownerid),
        None,
    )
    if source_score is None:
        return None

    segments = accelerated_inference_segments(source_score, source_turn)
    if segments is None:
        return None

    segment = _accelerated_segment_for_host_turn(segments, host_turn)
    if segment is None:
        return None

    return ResolvedInferenceTarget(
        observation=_observation_from_accelerated_segment(source_score, source_turn, segment),
        turn_info=source_turn,
        score=source_score,
    )


def _accelerated_segment_for_host_turn(
    segments: tuple[AcceleratedInferenceSegment, ...],
    host_turn: int,
) -> AcceleratedInferenceSegment | None:
    for segment in segments:
        if segment.host_turn == host_turn:
            return segment
    return None


def prior_turn_score_data_available(turn: TurnInfo) -> bool:
    """Return whether this turn has a prior scoreboard row to infer from."""
    turn_number = turn.settings.turn
    if turn_number <= 1:
        return False
    accelerated = accelerated_turn_count(turn.settings)
    if accelerated > 0 and turn_number < accelerated:
        return False
    return True


def _no_prior_turn_reason(turn: TurnInfo) -> str:
    if turn.settings.turn <= 1:
        return "first_turn"
    if needs_accelerated_backfill(turn.settings.turn, turn.settings):
        return "accelerated_backfill_unavailable"
    return "first_turn"


def is_after_ship_limit(turn: TurnInfo, score: Score) -> bool:
    """Return whether ship-limit queue rules apply for this player on this turn."""
    settings = turn.settings
    player_ships = score.capitalships + score.freighters
    if settings.shiplimittype != 0:
        player_limit = (
            settings.plsminships
            + settings.plsextraships
            + settings.plsshipsperplanet * score.planets
        )
        return player_ships >= player_limit
    total_ships = sum(
        other_score.capitalships + other_score.freighters for other_score in turn.scores
    )
    return total_ships >= settings.shiplimit


def build_inference_observation(score: Score, turn: TurnInfo) -> InferenceObservation:
    """Build solver observation for the reported host turn on this scoreboard row."""
    return _observation_from_deltas(
        score,
        turn,
        observation_deltas_from_score(score, turn),
    )


def _observation_from_deltas(
    score: Score,
    turn: TurnInfo,
    deltas: tuple[int, int, int, int],
    *,
    military_partition_slack_2x: int = SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
) -> InferenceObservation:
    military_delta_2x, warship_delta, freighter_delta, priority_point_delta = deltas
    return InferenceObservation(
        player_id=score.ownerid,
        turn=turn.settings.turn,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=priority_point_delta,
        starbases_owned=score.starbases,
        is_after_ship_limit=is_after_ship_limit(turn, score),
        military_partition_slack_2x=military_partition_slack_2x,
    )


def _observation_from_accelerated_segment(
    score: Score,
    turn: TurnInfo,
    segment: AcceleratedInferenceSegment,
) -> InferenceObservation:
    return _observation_from_deltas(
        score,
        turn,
        (
            segment.military_delta_2x,
            segment.warship_delta,
            segment.freighter_delta,
            segment.priority_point_delta,
        ),
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
    turn_number = turn.settings.turn
    resolved_observation = (
        observation if observation is not None else build_inference_observation(score, turn)
    )
    if not prior_turn_score_data_available(turn):
        backfill = _try_accelerated_backfill_inference(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if backfill is not None:
            return backfill
        return (
            _inference_api_payload(
                status=STATUS_NO_PRIOR_TURN,
                summary="Prior turn score data unavailable",
                solutions=(),
                diagnostics=build_inference_solver_diagnostics(
                    turn=turn_number,
                    observation=resolved_observation,
                    turn_info=turn,
                    extra={"reason": _no_prior_turn_reason(turn)},
                ),
            ),
            resolved_observation,
            None,
        )

    solve_catalog = catalog
    try:
        if solve_catalog is None:
            segments = accelerated_inference_segments(score, turn)
            if segments is not None:
                split_result = _run_accelerated_split_inference(score, turn, segments)
                payload, reported_observation, reported_catalog, _ = split_result
                return payload, reported_observation, reported_catalog
            result, solve_catalog, problem, policy_steps_attempted, step_diagnostics = (
                _solve_with_policy_ladder(
                    resolved_observation,
                    turn,
                )
            )
        else:
            policy_steps_attempted = [solve_catalog.policy_step_id]
            step_diagnostics = []
            problem = build_inference_problem(resolved_observation, solve_catalog)
            result = solve_inference_problem(problem)
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
        return (
            _inference_api_payload(
                status=STATUS_SOLVER_ERROR,
                summary="Build inference failed",
                solutions=(),
                diagnostics=build_inference_solver_diagnostics(
                    turn=turn_number,
                    observation=resolved_observation,
                    catalog=solve_catalog,
                    turn_info=turn,
                    extra={"error": str(exc)},
                ),
            ),
            resolved_observation,
            solve_catalog,
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
    if not needs_accelerated_backfill(turn.settings.turn, turn.settings):
        return None

    target_host_turn = scoreboard_host_turn(turn.settings.turn)
    source_turn_number = first_reliable_accelerated_scoreboard_turn(turn.settings)
    if target_host_turn is None or source_turn_number is None:
        return None

    source_turn = load_scoreboard_turn(source_turn_number)
    if source_turn is None:
        return None

    source_score = next(
        (row for row in source_turn.scores if row.ownerid == score.ownerid),
        None,
    )
    if source_score is None:
        return None

    segments = accelerated_inference_segments(source_score, source_turn)
    if segments is None:
        return None

    payload, _, _, segment_artifacts = _run_accelerated_split_inference(
        source_score,
        source_turn,
        segments,
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
                turn_info=source_turn,
                extra={
                    "accelerated_backfill": True,
                    "accelerated_backfill_source_turn": source_turn_number,
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
        segment_observation = _observation_from_accelerated_segment(score, turn, segment)
        if segment.segment_id == "reported_host_turn":
            reported_observation = segment_observation

        result, catalog, problem, policy_steps_attempted, step_diagnostics = (
            _solve_with_policy_ladder(
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


def _combo_counts_from_solution(solution: InferenceSolution) -> dict[str, int]:
    return {ship_build.combo_id: ship_build.count for ship_build in solution.ship_builds}


def _solution_fully_explained_by_ship_builds_only(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    if solution.actions:
        return False
    return _solution_satisfies_exact_hard_equalities(solution, observation, catalog)


def _solution_satisfies_exact_hard_equalities(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    military_sum = 0
    warship_sum = 0
    freighter_sum = 0
    for action in solution.actions:
        catalog_action = actions_by_id.get(action.action_id)
        if catalog_action is None:
            return False
        military_sum += catalog_action.score_delta_2x * action.count
        warship_sum += catalog_action.warship_delta * action.count
        freighter_sum += catalog_action.freighter_delta * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id.get(ship_build.combo_id)
        if combo is None:
            return False
        military_sum += combo.score_delta_2x * ship_build.count
        warship_sum += combo.warship_delta * ship_build.count
        freighter_sum += combo.freighter_delta * ship_build.count
    return (
        abs(military_sum - observation.military_delta_2x) <= observation.military_partition_slack_2x
        and warship_sum == observation.warship_delta
        and freighter_sum == observation.freighter_delta
    )


def _explained_military_score_2x(
    solution: InferenceSolution,
    catalog: ActionCatalog,
) -> int:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    explained = 0
    for action in solution.actions:
        catalog_action = actions_by_id[action.action_id]
        explained += catalog_action.score_delta_2x * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id[ship_build.combo_id]
        explained += combo.score_delta_2x * ship_build.count
    return explained


def _merge_exact_solutions(
    merged_solutions: list[InferenceSolution],
    seen_signatures: set[tuple[tuple[str, int], ...]],
    candidates: tuple[InferenceSolution, ...],
    *,
    resolved_max_solutions: int,
) -> int:
    new_solutions = 0
    for solution in candidates:
        signature = solution_signature(solution)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        merged_solutions.append(solution)
        new_solutions += 1
        if len(merged_solutions) >= resolved_max_solutions:
            break
    return new_solutions


def _solve_catalog(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    max_solutions: int,
    time_limit_seconds: float,
    military_score_alpha: int = 0,
    fixed_combo_counts: dict[str, int] | None = None,
    combo_count_neighborhood: int = 0,
) -> tuple[InferenceResult, InferenceProblem]:
    problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=max_solutions,
        time_limit_seconds=time_limit_seconds,
        military_score_alpha=military_score_alpha,
        fixed_combo_counts=fixed_combo_counts,
        combo_count_neighborhood=combo_count_neighborhood,
    )
    return solve_inference_problem(problem), problem


def _solve_seed_progression(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    seed: InferenceSolution,
    *,
    max_solutions: int,
    time_limit_seconds: float,
) -> tuple[InferenceResult | None, InferenceProblem | None]:
    fixed_counts = _combo_counts_from_solution(seed)
    if not fixed_counts:
        return None, None

    remaining_slots = max_solutions
    for neighborhood in (0, 1):
        if remaining_slots <= 0 or time_limit_seconds <= 0:
            break
        result, problem = _solve_catalog(
            observation,
            catalog,
            max_solutions=remaining_slots,
            time_limit_seconds=time_limit_seconds,
            fixed_combo_counts=fixed_counts,
            combo_count_neighborhood=neighborhood,
        )
        if result.solutions:
            return result, problem

    result, problem = _solve_catalog(
        observation,
        catalog,
        max_solutions=remaining_slots,
        time_limit_seconds=time_limit_seconds,
    )
    if result.solutions:
        return result, problem
    return None, None


def _policy_step_diagnostics(
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    catalog: ActionCatalog,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    band_residual_2x: int | None,
) -> dict[str, object]:
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        observation.player_id,
        policy_step,
    )
    return {
        "policyStepId": policy_step.id,
        "policyStepIndex": policy_step_index,
        "policyStepsAttempted": policy_step_index + 1,
        "constraintSnapshot": policy_step.constraint_snapshot(),
        "resolvedEligibleEngineIds": sorted(catalog_context.eligible_engine_ids),
        "resolvedEligibleBeamIds": sorted(catalog_context.eligible_beam_ids),
        "resolvedEligibleTorpIds": sorted(catalog_context.eligible_torp_ids),
        "resolvedBuildableHullIds": sorted(catalog_context.buildable_hull_ids),
        "alpha": policy_step.alpha,
        "comboCount": len(catalog.ship_build_combos),
        "seedCount": seed_count,
        "bandResidual2x": band_residual_2x,
    }


def _solve_with_policy_ladder(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    policy_path: Path | None = None,
    max_solutions: int | None = None,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[
    InferenceResult,
    ActionCatalog,
    InferenceProblem,
    list[str],
    list[dict[str, object]],
]:
    """Walk the YAML inference search tier ladder with band seed carry-forward."""
    started_at = time.monotonic()
    policy_steps = resolve_tier_policies(policy_path)
    policy_steps_attempted: list[str] = []
    step_diagnostics: list[dict[str, object]] = []
    merged_solutions: list[InferenceSolution] = []
    seen_signatures: set[tuple[tuple[str, int], ...]] = set()
    catalog: ActionCatalog | None = None
    problem: InferenceProblem | None = None
    last_status = STATUS_NO_EXACT_SOLUTION
    last_diagnostics: dict[str, object] = {}
    resolved_max_solutions = max_solutions if max_solutions is not None else 20
    time_limited = False
    band_seeds: list[InferenceSolution] = []
    best_band_residual_2x: int | None = None
    prior_combo_ids: frozenset[str] | None = None
    prior_aggregate_action_ids: frozenset[str] | None = None
    ladder_early_stop_reason: str | None = None

    for step_index, policy_step in enumerate(policy_steps):
        remaining = time_limit_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            time_limited = True
            break

        policy_steps_attempted.append(policy_step.id)
        catalog = build_action_catalog_from_turn(
            observation,
            turn,
            policy_step=policy_step,
            policy_step_index=step_index,
        )
        current_combo_ids = frozenset(combo.combo_id for combo in catalog.ship_build_combos)
        added_combo_ids = (
            current_combo_ids if prior_combo_ids is None else current_combo_ids - prior_combo_ids
        )
        if added_combo_ids:
            merged_solutions.clear()
            seen_signatures.clear()
        prior_combo_ids = current_combo_ids
        current_aggregate_action_ids = frozenset(action.id for action in catalog.aggregate_actions)
        added_aggregate_action_ids = (
            current_aggregate_action_ids
            if prior_aggregate_action_ids is None
            else current_aggregate_action_ids - prior_aggregate_action_ids
        )
        prior_aggregate_action_ids = current_aggregate_action_ids

        remaining_slots = max(0, resolved_max_solutions - len(merged_solutions))
        if remaining_slots == 0:
            break

        new_exact_before_step = len(merged_solutions)
        seeds_for_step = list(band_seeds)
        band_seeds = []

        for seed in seeds_for_step[: policy_step.max_seeds]:
            seed_remaining = time_limit_seconds - (time.monotonic() - started_at)
            if seed_remaining <= 0:
                time_limited = True
                break
            seed_result, seed_problem = _solve_seed_progression(
                observation,
                catalog,
                seed,
                max_solutions=remaining_slots,
                time_limit_seconds=seed_remaining,
            )
            if seed_result is None or seed_problem is None:
                continue
            if seed_result.status == STATUS_INVALID_PROBLEM:
                last_status = seed_result.status
                last_diagnostics = dict(seed_result.diagnostics)
                problem = seed_problem
                break
            remaining_slots = max(0, resolved_max_solutions - len(merged_solutions))
            if remaining_slots == 0:
                break
            _merge_exact_solutions(
                merged_solutions,
                seen_signatures,
                seed_result.solutions,
                resolved_max_solutions=resolved_max_solutions,
            )
            problem = seed_problem
            if seed_result.status == STATUS_TIME_LIMITED:
                time_limited = True

        if last_status == STATUS_INVALID_PROBLEM:
            break

        remaining = time_limit_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            time_limited = True
            break
        remaining_slots = max(0, resolved_max_solutions - len(merged_solutions))
        if remaining_slots == 0:
            break

        exact_result, problem = _solve_catalog(
            observation,
            catalog,
            max_solutions=remaining_slots,
            time_limit_seconds=remaining,
        )
        last_status = exact_result.status
        last_diagnostics = dict(exact_result.diagnostics)
        if exact_result.status == STATUS_INVALID_PROBLEM:
            break

        if exact_result.solutions:
            _merge_exact_solutions(
                merged_solutions,
                seen_signatures,
                exact_result.solutions,
                resolved_max_solutions=resolved_max_solutions,
            )
            if exact_result.status == STATUS_TIME_LIMITED:
                time_limited = True

        band_residual_2x: int | None = None
        if not exact_result.solutions and policy_step.alpha > 0:
            remaining = time_limit_seconds - (time.monotonic() - started_at)
            if remaining > 0:
                band_result, band_problem = _solve_catalog(
                    observation,
                    catalog,
                    max_solutions=policy_step.max_seeds,
                    time_limit_seconds=remaining,
                    military_score_alpha=policy_step.alpha,
                )
                problem = band_problem
                last_diagnostics = dict(band_result.diagnostics)
                if band_result.solutions:
                    band_seeds = list(band_result.solutions[: policy_step.max_seeds])
                    best_solution = band_result.solutions[0]
                    explained = _explained_military_score_2x(best_solution, catalog)
                    band_residual_2x = observation.military_delta_2x - explained
                    if best_band_residual_2x is None or band_residual_2x < best_band_residual_2x:
                        best_band_residual_2x = band_residual_2x
                elif band_result.status == STATUS_INVALID_PROBLEM:
                    last_status = band_result.status
                    break

        step_diagnostics.append(
            _policy_step_diagnostics(
                policy_step=policy_step,
                policy_step_index=step_index,
                catalog=catalog,
                turn=turn,
                observation=observation,
                seed_count=len(seeds_for_step),
                band_residual_2x=band_residual_2x,
            )
        )

        if merged_solutions and _solution_fully_explained_by_ship_builds_only(
            merged_solutions[0],
            observation,
            catalog,
        ):
            break

        if (
            len(merged_solutions) == new_exact_before_step
            and len(merged_solutions) > 0
            and not added_combo_ids
            and not added_aggregate_action_ids
        ):
            ladder_early_stop_reason = "no_new_exact_signatures"
            break

    if catalog is None or problem is None:
        first_step = policy_steps[0]
        policy_steps_attempted.append(first_step.id)
        catalog = build_action_catalog_from_turn(
            observation,
            turn,
            policy_step=first_step,
            policy_step_index=0,
        )
        problem = build_inference_problem(observation, catalog, max_solutions=max_solutions)
        tier_result = solve_inference_problem(problem)
        last_status = tier_result.status
        last_diagnostics = dict(tier_result.diagnostics)
        _merge_exact_solutions(
            merged_solutions,
            seen_signatures,
            tier_result.solutions,
            resolved_max_solutions=resolved_max_solutions,
        )

    merged_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
    if merged_solutions:
        if _solution_satisfies_exact_hard_equalities(
            merged_solutions[0],
            observation,
            catalog,
        ):
            status = STATUS_EXACT
        else:
            status = STATUS_TIME_LIMITED if time_limited else STATUS_EXACT
    else:
        status = STATUS_TIME_LIMITED if time_limited else last_status

    stopped_reason = ladder_early_stop_reason or last_diagnostics.get("stopped_reason", "exhausted")
    result = InferenceResult(
        status=status,
        solutions=tuple(merged_solutions),
        diagnostics={
            **last_diagnostics,
            "policy_step_id": catalog.policy_step_id,
            "policy_step_index": catalog.policy_step_index,
            "solution_count": len(merged_solutions),
            "best_band_residual_2x": best_band_residual_2x,
            "stopped_reason": stopped_reason,
        },
    )
    return result, catalog, problem, policy_steps_attempted, step_diagnostics


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
