"""Scores analytic integration for military score build inference."""

from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
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
    player_by_id,
)
from api.analytics.military_score_inference.constraints import (
    InferenceHardConstraints,
    observation_to_constraints_payload,
)
from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.host_turn_targets import (
    functional_host_turn_target_from_segment_payload,
    host_turn_functional_target_to_wire_dict,
    host_turn_targets_from_wire_event,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_accelerated import (
    run_accelerated_split_inference,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_SOLVER_ERROR,
    format_inference_summary,
    inference_api_payload,
    inference_result_to_api_payload,
    no_prior_turn_inference_api_payload,
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
    observation_from_deltas,
    prior_scoreboard_row_score,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.solver import (
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)
from api.models.game import TurnInfo
from api.models.player import Score

__all__ = [
    "is_after_ship_limit",
    "prior_turn_score_data_available",
    "run_inference_with_artifacts",
]


def build_inference_observation(
    score: Score,
    turn: TurnInfo,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> InferenceObservation:
    """Build solver observation for the reported host turn on this scoreboard row."""
    prior_score = prior_scoreboard_row_score(score, turn, load_scoreboard_turn)
    military_delta_2x, warship_delta, freighter_delta, priority_point_delta, delta_source = (
        observation_deltas_from_score(score, turn, prior_score=prior_score)
    )
    return observation_from_deltas(
        score,
        turn,
        (military_delta_2x, warship_delta, freighter_delta, priority_point_delta),
        scoreboard_delta_source=delta_source,
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
    """Structured solver diagnostics for the diagnostics panel.

    Solver-owned keys (ranking heuristics, diversity caps, bin indicators, etc.)
    must come from ``solver`` -- typically ``InferenceResult.diagnostics`` plus
    status. This function adds analytic-level context (constraints display,
    catalog snapshot, turn metadata) without recomputing solver diagnostics.
    """
    solver_data = solver or {}
    diversity_caps_applied = solver_data.get("diversityCapsApplied")
    if not isinstance(diversity_caps_applied, list):
        diversity_caps_applied = None

    payload: dict[str, object] = {"turn": turn}
    if observation is not None:
        hard_constraints = (
            InferenceHardConstraints.from_problem(problem)
            if problem is not None
            else InferenceHardConstraints()
        )
        aggregate_action_ids = (
            frozenset(action.id for action in problem.aggregate_actions)
            if problem is not None
            else None
        )
        payload["constraints"] = observation_to_constraints_payload(
            observation,
            hard_constraints=hard_constraints,
            aggregate_action_ids=aggregate_action_ids,
            diversity_caps_applied=diversity_caps_applied,
        )
    if catalog is not None:
        payload["actionCatalog"] = catalog_to_actions_payload(
            catalog,
            turn=turn_info,
            observation=observation,
        )
        payload.update(catalog.diagnostics())
    ranking_heuristics = solver_data.get("rankingHeuristics")
    if isinstance(ranking_heuristics, dict):
        payload["rankingHeuristics"] = ranking_heuristics
    if solver is not None:
        payload["solver"] = {
            key: value
            for key, value in solver_data.items()
            if key not in ("rankingHeuristics", "diversityCapsApplied")
        }
    if extra:
        payload.update(extra)
    return payload


def _no_prior_turn_inference_result(
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    return (
        no_prior_turn_inference_api_payload(turn, resolved_observation),
        resolved_observation,
        None,
    )


def _run_accelerated_backfill_inference(
    score: Score,
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    backfill = _try_accelerated_backfill_inference(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
    )
    if backfill is not None:
        return backfill
    return _no_prior_turn_inference_result(turn, resolved_observation)


def _run_accelerated_split_inference_path(
    score: Score,
    turn: TurnInfo,
    segments: tuple[AcceleratedInferenceSegment, ...],
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    payload, reported_observation, reported_catalog, _ = run_accelerated_split_inference(
        score,
        turn,
        segments,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
    )
    return payload, reported_observation, reported_catalog


def _run_policy_ladder_inference(
    resolved_observation: InferenceObservation,
    turn: TurnInfo,
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[
    InferenceResult,
    ActionCatalog | None,
    InferenceProblem | None,
    list[str],
    list[dict[str, object]],
]:
    return solve_with_policy_ladder(
        resolved_observation,
        turn,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
        time_limit_seconds=time_limit_seconds,
    )


def _run_corpus_prebuilt_inference(
    resolved_observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    turn: TurnInfo | None = None,
) -> tuple[InferenceResult, ActionCatalog, InferenceProblem, list[str], list[dict[str, object]]]:
    race_id = (
        player_by_id(turn, resolved_observation.player_id).raceid if turn is not None else None
    )
    problem = build_inference_problem(resolved_observation, catalog, race_id=race_id)
    result = solve_inference_problem(problem)
    return result, catalog, problem, [catalog.policy_step_id], []


def _solver_error_inference_result(
    turn: TurnInfo,
    resolved_observation: InferenceObservation,
    solve_catalog: ActionCatalog | None,
    exc: Exception,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    return (
        inference_api_payload(
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
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    if path == InferencePath.ACCELERATED_SPLIT:
        assert accelerated_segments is not None
        return _run_accelerated_split_inference_path(
            score,
            turn,
            accelerated_segments,
            resolved_mask=resolved_mask,
            fleet_torp_overlay=fleet_torp_overlay,
        )

    solve_catalog = catalog
    try:
        if path == InferencePath.POLICY_LADDER:
            result, solve_catalog, problem, policy_steps_attempted, step_diagnostics = (
                _run_policy_ladder_inference(
                    resolved_observation,
                    turn,
                    resolved_mask=resolved_mask,
                    fleet_torp_overlay=fleet_torp_overlay,
                    time_limit_seconds=time_limit_seconds,
                )
            )
        else:
            assert path == InferencePath.CORPUS_PREBUILT
            assert solve_catalog is not None
            result, solve_catalog, problem, policy_steps_attempted, step_diagnostics = (
                _run_corpus_prebuilt_inference(resolved_observation, solve_catalog, turn=turn)
            )
        if solve_catalog is None or problem is None:
            return (
                inference_api_payload(
                    status=result.status,
                    summary=format_inference_summary(result),
                    solutions=result.solutions,
                    diagnostics=build_inference_solver_diagnostics(
                        turn=turn.settings.turn,
                        observation=resolved_observation,
                        turn_info=turn,
                        solver={"status": result.status, **result.diagnostics},
                        extra={
                            "policy_steps_attempted": policy_steps_attempted,
                            "policy_step_attempts": step_diagnostics,
                        },
                    ),
                ),
                resolved_observation,
                None,
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
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[dict[str, object], InferenceObservation, ActionCatalog | None]:
    """Run inference once; return API payload plus observation and catalog for re-checks.

    When ``observation`` and ``catalog`` are supplied (e.g. corpus harness), they are
    reused for solving and returned unchanged so constraint re-check uses the same
    catalog instance as coverage evaluation.
    """
    resolved_observation = (
        observation
        if observation is not None
        else build_inference_observation(score, turn, load_scoreboard_turn=load_scoreboard_turn)
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
            resolved_mask=resolved_mask,
            fleet_torp_overlay=fleet_torp_overlay,
        )
    return _run_solver_inference_path(
        path,
        score,
        turn,
        resolved_observation,
        catalog=catalog,
        accelerated_segments=accelerated_segments,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
        time_limit_seconds=time_limit_seconds,
    )


def _try_accelerated_backfill_inference(
    score: Score,
    turn: TurnInfo,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
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

    payload, _, _, segment_artifacts = run_accelerated_split_inference(
        backfill_source.source_score,
        backfill_source.source_turn,
        backfill_source.segments,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
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
            "hostTurnTargets": [
                host_turn_functional_target_to_wire_dict(
                    functional_host_turn_target_from_segment_payload(segment_payload),
                ),
            ],
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
    for target in host_turn_targets_from_wire_event(split_payload):
        if target.host_turn == host_turn:
            return host_turn_functional_target_to_wire_dict(target)

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


def infer_military_score_build(score: Score, turn: TurnInfo) -> dict[str, object]:
    """Run build inference for one scoreboard row, isolating failures to that row."""
    payload, _, _ = run_inference_with_artifacts(score, turn)
    return payload
