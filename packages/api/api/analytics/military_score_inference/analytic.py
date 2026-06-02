"""Scores analytic integration for military score build inference."""

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.solver import (
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)
from api.models.game import TurnInfo
from api.models.player import Score

STATUS_NO_PRIOR_TURN = "no_prior_turn"
STATUS_SOLVER_ERROR = "solver_error"


def prior_turn_score_data_available(turn: TurnInfo) -> bool:
    """Return whether this turn has a prior scoreboard row to infer from."""
    return turn.settings.turn > 1


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
    """Build solver observation from one scoreboard row and turn context."""
    return InferenceObservation(
        player_id=score.ownerid,
        turn=turn.settings.turn,
        military_delta_2x=2 * score.militarychange,
        warship_delta=score.shipchange,
        freighter_delta=score.freighterchange,
        priority_point_delta=score.prioritypointchange,
        starbases_owned=score.starbases,
        is_after_ship_limit=is_after_ship_limit(turn, score),
    )


def observation_to_constraints_payload(observation: InferenceObservation) -> dict[str, object]:
    """Serialize hard solver constraints for diagnostics."""
    return {
        "turn": observation.turn,
        "playerId": observation.player_id,
        "militaryDelta2x": observation.military_delta_2x,
        "warshipDelta": observation.warship_delta,
        "freighterDelta": observation.freighter_delta,
        "priorityPointDelta": observation.priority_point_delta,
        "starbasesOwned": observation.starbases_owned,
        "isAfterShipLimit": observation.is_after_ship_limit,
        "appliedEqualities": [
            f"sum(scoreDelta2x * count) == {observation.military_delta_2x}",
            f"sum(warshipDelta * count) == {observation.warship_delta}",
            f"sum(freighterDelta * count) == {observation.freighter_delta}",
            f"sum(priorityPointDelta * count) == {observation.priority_point_delta}",
            f"sum(buildSlotUsage * count) <= {observation.starbases_owned}",
        ],
    }


def catalog_to_actions_payload(
    catalog: ActionCatalog,
    *,
    turn: TurnInfo | None = None,
    observation: InferenceObservation | None = None,
) -> dict[str, object]:
    """Serialize the bounded action catalog for diagnostics."""
    ship_build_actions = [action for action in catalog.actions if action.id.startswith("build_")]
    payload: dict[str, object] = {
        "catalogSize": catalog.catalog_size,
        "shipBuildActionCount": len(ship_build_actions),
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
            for action in catalog.actions
        ],
        "shipBuildActions": [
            {
                "id": action.id,
                "label": action.label,
                "upperBound": action.upper_bound,
                "scoreDelta2x": action.score_delta_2x,
            }
            for action in ship_build_actions
        ],
    }
    if turn is not None and observation is not None:
        from api.analytics.military_score_inference.actions import buildable_hull_ids_for_player

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
            "shipBuildActionIds": [action.id for action in ship_build_actions],
        }
    return payload


def build_inference_solver_diagnostics(
    *,
    turn: int,
    observation: InferenceObservation | None = None,
    catalog: ActionCatalog | None = None,
    turn_info: TurnInfo | None = None,
    solver: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Structured solver diagnostics for the diagnostics panel."""
    payload: dict[str, object] = {"turn": turn}
    if observation is not None:
        payload["constraints"] = observation_to_constraints_payload(observation)
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


def infer_military_score_build(score: Score, turn: TurnInfo) -> dict[str, object]:
    """Run build inference for one scoreboard row, isolating failures to that row."""
    turn_number = turn.settings.turn
    if not prior_turn_score_data_available(turn):
        observation = build_inference_observation(score, turn)
        return _inference_api_payload(
            status=STATUS_NO_PRIOR_TURN,
            summary="Prior turn score data unavailable",
            solutions=(),
            diagnostics=build_inference_solver_diagnostics(
                turn=turn_number,
                observation=observation,
                turn_info=turn,
                extra={"reason": "first_turn"},
            ),
        )

    observation = build_inference_observation(score, turn)
    catalog: ActionCatalog | None = None
    try:
        catalog = build_action_catalog_from_turn(observation, turn)
        problem = build_inference_problem(observation, catalog)
        result = solve_inference_problem(problem)
        return inference_result_to_api_payload(result, catalog, observation, turn)
    except Exception as exc:
        return _inference_api_payload(
            status=STATUS_SOLVER_ERROR,
            summary="Build inference failed",
            solutions=(),
            diagnostics=build_inference_solver_diagnostics(
                turn=turn_number,
                observation=observation,
                catalog=catalog,
                turn_info=turn,
                extra={"error": str(exc)},
            ),
        )


def inference_result_to_api_payload(
    result: InferenceResult,
    catalog: ActionCatalog,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape a solver result into the Core scores row inference object."""
    solver_diagnostics = {
        "status": result.status,
        **result.diagnostics,
    }
    diagnostics = build_inference_solver_diagnostics(
        turn=turn.settings.turn,
        observation=observation,
        catalog=catalog,
        turn_info=turn,
        solver=solver_diagnostics,
    )
    return _inference_api_payload(
        status=result.status,
        summary=format_inference_summary(result),
        solutions=result.solutions,
        diagnostics=diagnostics,
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
    return "; ".join(parts) if parts else "no actions"


def _inference_api_payload(
    *,
    status: str,
    summary: str,
    solutions: tuple[InferenceSolution, ...],
    diagnostics: dict[str, object],
) -> dict[str, object]:
    return {
        "status": status,
        "summary": summary,
        "solutionCount": len(solutions),
        "isComplete": status != STATUS_TIME_LIMITED,
        "solutions": [_serialize_solution(solution) for solution in solutions],
        "diagnostics": diagnostics,
    }


def _serialize_solution(solution: InferenceSolution) -> dict[str, object]:
    return {
        "objectiveValue": solution.objective_value,
        "actions": [
            {
                "actionId": action.action_id,
                "label": action.label,
                "count": action.count,
            }
            for action in solution.actions
        ],
    }
