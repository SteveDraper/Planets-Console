"""API payload serialization for military score build inference results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.post_unsat_placeholders import (
    post_unsat_placeholders_from_turn,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    fleet_torp_complete_wire_fields_from_diagnostics,
)
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)
from api.analytics.military_score_inference.ship_first_overshoot import leftover_military_2x
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)
from api.analytics.military_score_inference.tier_emission_ledger import (
    compact_tier_emissions_from_step_diagnostics,
)
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
    UNCHARACTERIZED_ROSTER_SUMMARY,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    LatticeSignature,
    PlaceholderDeparture,
    UnknownLossLeftover,
)
from api.models.game import TurnInfo
from api.serialization.uncharacterized_roster import (
    lattice_signature_to_json,
    leftover_to_json,
    placeholder_departure_to_json,
)

STATUS_NO_PRIOR_TURN = "no_prior_turn"
STATUS_PLAYER_NOT_FOUND = "player_not_found"
STATUS_SOLVER_ERROR = "solver_error"
STATUS_VIEWPOINT_OWNER = "viewpoint_owner"
STATUS_DEAD = "dead"
STATUS_FULL_ALLIANCE = "full_alliance"
STATUS_HORWASP = "horwasp"

INFERENCE_ADMISSION_SKIP_STATUSES = frozenset(
    {
        STATUS_VIEWPOINT_OWNER,
        STATUS_DEAD,
        STATUS_FULL_ALLIANCE,
        STATUS_HORWASP,
        STATUS_NO_PRIOR_TURN,
        STATUS_PLAYER_NOT_FOUND,
    }
)
FUNCTIONAL_LEFTOVER_STATUSES = frozenset(
    {
        STATUS_MODERATE_RESIDUAL,
        STATUS_MINE_SCORE_RESIDUAL,
        STATUS_NO_EXACT_SOLUTION,
    }
)
PERSISTABLE_INFERENCE_STATUSES = frozenset(
    {
        STATUS_EXACT,
        STATUS_NO_EXACT_SOLUTION,
        STATUS_MODERATE_RESIDUAL,
        STATUS_MINE_SCORE_RESIDUAL,
        STATUS_UNCHARACTERIZED_ROSTER,
    }
)
FALLBACK_COMPLETE_PERSISTED_STATUSES = INFERENCE_ADMISSION_SKIP_STATUSES | frozenset(
    {
        STATUS_INVALID_PROBLEM,
        STATUS_SOLVER_ERROR,
    }
)
# Row statuses that map to export searchStatus=complete. Derived from
# persistable | fallback-complete; stopped / time_limited stay outside this set.
COMPLETE_INFERENCE_SEARCH_STATUSES = (
    PERSISTABLE_INFERENCE_STATUSES | FALLBACK_COMPLETE_PERSISTED_STATUSES
)


@dataclass(frozen=True)
class InferenceProductPayload:
    """Product status, placeholders, leftover, and lattice signatures."""

    status: str | None = None
    placeholders: list[dict[str, object]] | None = None
    unexplained_military_delta_2x: int | None = None
    leftover: dict[str, object] | None = None
    lattice_signatures: list[dict[str, object]] | None = None


def product_payload_fields(
    status: str,
    *,
    placeholders: list[dict[str, object]] | None = None,
    leftover: int | None = None,
    tagged_leftover: dict[str, object] | None = None,
    lattice_signatures: list[dict[str, object]] | None = None,
) -> InferenceProductPayload:
    """Return product fields for persist, stream, export, and host-turn targets.

    Residual / ``no_exact_solution`` expose point leftover and ``placeholders``
    (empty list if missing). Skip rows expose empty ``placeholders`` and omit
    leftover. ``uncharacterized_roster`` exposes empty ``placeholders`` when
    omitted, never a point leftover, and keeps tagged leftover and lattice
    signatures when provided. Other statuses omit leftover and omit
    placeholders unless the source already carried them.
    """
    resolved_placeholders = placeholders
    if (
        status in FUNCTIONAL_LEFTOVER_STATUSES
        or status in INFERENCE_ADMISSION_SKIP_STATUSES
        or status == STATUS_UNCHARACTERIZED_ROSTER
    ) and resolved_placeholders is None:
        resolved_placeholders = []
    is_roster = status == STATUS_UNCHARACTERIZED_ROSTER
    return InferenceProductPayload(
        status=status,
        placeholders=resolved_placeholders,
        unexplained_military_delta_2x=(
            leftover if status in FUNCTIONAL_LEFTOVER_STATUSES else None
        ),
        leftover=tagged_leftover if is_roster else None,
        lattice_signatures=lattice_signatures if is_roster else None,
    )


def _optional_point_leftover(data: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def product_payload_from_mapping(
    data: dict[str, object],
    *,
    status: str,
    leftover_fallback: int | None = None,
) -> InferenceProductPayload:
    """Decode product slots from a wire or persistence mapping, then apply policy."""
    raw_placeholders = data.get("placeholders")
    placeholders = (
        [entry for entry in raw_placeholders if isinstance(entry, dict)]
        if isinstance(raw_placeholders, list)
        else None
    )
    leftover = _optional_point_leftover(
        data,
        "unexplainedMilitaryDelta2x",
        "unexplained_military_delta_2x",
    )
    leftover_source = leftover if leftover is not None else leftover_fallback
    tagged = data.get("leftover")
    raw_signatures = data.get("latticeSignatures")
    if raw_signatures is None:
        raw_signatures = data.get("lattice_signatures")
    return product_payload_fields(
        status,
        placeholders=placeholders,
        leftover=leftover_source,
        tagged_leftover=tagged if isinstance(tagged, dict) else None,
        lattice_signatures=(
            [entry for entry in raw_signatures if isinstance(entry, dict)]
            if isinstance(raw_signatures, list)
            else None
        ),
    )


def apply_product_payload_fields(
    payload: dict[str, object],
    product: InferenceProductPayload,
    *,
    unexplained_key: str = "unexplainedMilitaryDelta2x",
    signatures_key: str = "latticeSignatures",
) -> dict[str, object]:
    """Copy present product slots onto a wire or persistence dict."""
    if product.placeholders is not None:
        payload["placeholders"] = product.placeholders
    if product.unexplained_military_delta_2x is not None:
        payload[unexplained_key] = product.unexplained_military_delta_2x
    if product.leftover is not None:
        payload["leftover"] = product.leftover
    if product.lattice_signatures is not None:
        payload[signatures_key] = product.lattice_signatures
    return payload


def product_payload_from_result(
    result: InferenceResult,
    *,
    leftover: int | None = None,
    placeholders: list[dict[str, object]] | None = None,
) -> InferenceProductPayload:
    """Encode roster leftover/signatures from a solver result, then apply policy."""
    resolved_placeholders = placeholders
    if resolved_placeholders is None and result.placeholders:
        resolved_placeholders = list(result.placeholders)
    tagged_leftover: dict[str, object] | None = None
    signatures: list[dict[str, object]] | None = None
    if result.status == STATUS_UNCHARACTERIZED_ROSTER:
        resolved_placeholders, tagged_leftover, signatures = _uncharacterized_roster_wire_fields(
            result.leftover,
            result.placeholder_departures,
            result.lattice_signatures,
            resolved_placeholders,
        )
    return product_payload_fields(
        result.status,
        placeholders=resolved_placeholders,
        leftover=leftover,
        tagged_leftover=tagged_leftover,
        lattice_signatures=signatures,
    )


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
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> dict[str, object]:
    """Shape a solver result into the Core scores row inference object."""
    from api.analytics.military_score_inference.analytic import (
        build_inference_solver_diagnostics,
    )

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
    leftover_2x = _functional_leftover_2x(
        result.status,
        observation,
        rank1_overshoot_2x=(
            leftover_military_2x(result.solutions[0], observation, catalog)
            if result.status == STATUS_MINE_SCORE_RESIDUAL and result.solutions
            else None
        ),
    )
    placeholders = None
    if result.status in FUNCTIONAL_LEFTOVER_STATUSES:
        if result.status == STATUS_MINE_SCORE_RESIDUAL and result.solutions:
            placeholders = []
        else:
            placeholders = post_unsat_placeholders_from_turn(
                observation,
                turn,
                resolved_mask=resolved_mask,
            )
    if result.status == STATUS_UNCHARACTERIZED_ROSTER:
        placeholders = list(result.placeholders)
    return inference_api_payload(
        status=result.status,
        summary=format_inference_summary(
            result,
            unexplained_military_delta_2x=leftover_2x,
        ),
        solutions=result.solutions,
        diagnostics=diagnostics,
        observation=observation,
        catalog=catalog,
        placeholders=placeholders,
        unexplained_military_delta_2x=leftover_2x,
        leftover=result.leftover,
        placeholder_departures=result.placeholder_departures,
        lattice_signatures=result.lattice_signatures,
        departure_pins=result.departure_pins,
    )


def _functional_leftover_2x(
    status: str,
    observation: InferenceObservation | None,
    *,
    rank1_overshoot_2x: int | None = None,
) -> int | None:
    if status not in FUNCTIONAL_LEFTOVER_STATUSES:
        return None
    if status == STATUS_MINE_SCORE_RESIDUAL and rank1_overshoot_2x is not None:
        return rank1_overshoot_2x
    if observation is None:
        return None
    return observation.military_delta_2x


def _functional_leftover_status_summary(
    status: str,
    leftover_2x: int | None,
) -> str | None:
    if status == STATUS_MODERATE_RESIDUAL:
        if leftover_2x is None:
            return "Moderate military leftover"
        return f"Moderate military leftover ({leftover_2x // 2})"
    if status == STATUS_MINE_SCORE_RESIDUAL:
        if leftover_2x is None:
            return "Mine-score leftover"
        return f"Mine-score leftover ({leftover_2x // 2})"
    if status == STATUS_NO_EXACT_SOLUTION:
        return "No feasible build explanation found"
    return None


def format_inference_summary(
    result: InferenceResult,
    *,
    unexplained_military_delta_2x: int | None = None,
) -> str:
    """Return compact row-level summary text for the inference column."""
    leftover_summary = _functional_leftover_status_summary(
        result.status,
        unexplained_military_delta_2x,
    )
    if leftover_summary is not None:
        return leftover_summary
    if result.status == STATUS_INVALID_PROBLEM:
        reason = result.diagnostics.get("reason")
        if isinstance(reason, str) and reason:
            return f"Invalid inference problem: {reason}"
        return "Invalid inference problem"
    if result.status == STATUS_SOLVER_ERROR:
        return "Build inference failed"
    if result.status == STATUS_STOPPED:
        if result.solutions:
            return f"Halted with {len(result.solutions)} held solution(s)"
        return "Build inference halted"
    if result.status == STATUS_TIME_LIMITED and not result.solutions:
        return "Inference timed out before finding a solution"
    if result.status == STATUS_UNCHARACTERIZED_ROSTER:
        return UNCHARACTERIZED_ROSTER_SUMMARY
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


def _inference_row_is_complete(
    status: str,
    solutions: tuple[InferenceSolution, ...],
) -> bool:
    if status == STATUS_UNCHARACTERIZED_ROSTER:
        return True
    return status != STATUS_TIME_LIMITED or len(solutions) == 0


def _uncharacterized_roster_wire_fields(
    leftover: UnknownLossLeftover | None,
    placeholder_departures: tuple[PlaceholderDeparture, ...],
    lattice_signatures: tuple[LatticeSignature, ...],
    hidden_builds: list[dict[str, object]] | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None, list[dict[str, object]]]:
    placeholders = [
        *(hidden_builds or []),
        *(placeholder_departure_to_json(departure) for departure in placeholder_departures),
    ]
    leftover_wire = leftover_to_json(leftover) if leftover is not None else None
    signatures_wire = [lattice_signature_to_json(signature) for signature in lattice_signatures]
    return placeholders, leftover_wire, signatures_wire


def inference_api_payload(
    *,
    status: str,
    summary: str,
    solutions: tuple[InferenceSolution, ...],
    diagnostics: dict[str, object],
    observation: InferenceObservation | None = None,
    catalog: ActionCatalog | None = None,
    placeholders: list[dict[str, object]] | None = None,
    unexplained_military_delta_2x: int | None = None,
    leftover: UnknownLossLeftover | None = None,
    placeholder_departures: tuple[PlaceholderDeparture, ...] = (),
    lattice_signatures: tuple[LatticeSignature, ...] = (),
    departure_pins: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    fleet_torp_input_status, fleet_torp_overlay_belief_set_torp_ids = (
        fleet_torp_complete_wire_fields_from_diagnostics(diagnostics)
    )
    leftover_2x = (
        unexplained_military_delta_2x
        if unexplained_military_delta_2x is not None
        else _functional_leftover_2x(status, observation)
    )
    leftover_summary = _functional_leftover_status_summary(status, leftover_2x)
    leftover_wire: dict[str, object] | None = None
    signatures_wire: list[dict[str, object]] | None = None
    if status == STATUS_UNCHARACTERIZED_ROSTER:
        placeholders, leftover_wire, signatures_wire = _uncharacterized_roster_wire_fields(
            leftover,
            placeholder_departures,
            lattice_signatures,
            placeholders,
        )
    product = product_payload_fields(
        status,
        leftover=leftover_2x,
        placeholders=placeholders,
        tagged_leftover=leftover_wire,
        lattice_signatures=signatures_wire,
    )
    payload: dict[str, object] = {
        "status": product.status,
        "summary": leftover_summary if leftover_summary is not None else summary,
        "solutionCount": len(solutions),
        # Zero-solution timeouts are terminal failures (visible error in the SPA).
        # Timeouts that already hold solutions stay incomplete so partial top-K can
        # keep streaming until a durable stop/persist path closes the row.
        # Uncharacterized roster is a closed product (no in-flight solution events).
        "isComplete": _inference_row_is_complete(status, solutions),
        "solutions": (
            [
                _serialize_solution_with_arithmetic(
                    observation,
                    catalog,
                    solution,
                    assign_intervals_to_observed_slack=status != STATUS_MINE_SCORE_RESIDUAL,
                )
                for solution in solutions
            ]
            if observation is not None and catalog is not None
            else [serialize_solution_without_arithmetic(solution) for solution in solutions]
        ),
        "diagnostics": diagnostics,
    }
    apply_product_payload_fields(payload, product)
    if departure_pins:
        payload["departurePins"] = departure_pins
    if fleet_torp_input_status is not None:
        payload["fleetTorpInputStatus"] = fleet_torp_input_status
    if fleet_torp_overlay_belief_set_torp_ids is not None:
        payload["fleetTorpOverlayBeliefSetTorpIds"] = fleet_torp_overlay_belief_set_torp_ids
    attempts = diagnostics.get("policy_step_attempts")
    if isinstance(attempts, list) and attempts:
        tier_emissions = compact_tier_emissions_from_step_diagnostics(attempts)
        if tier_emissions:
            payload["tierEmissions"] = tier_emissions
    return payload


def _serialize_solution_actions(
    solution: InferenceSolution,
) -> list[dict[str, object]]:
    return [
        {
            "actionId": action.action_id,
            "label": action.label,
            "count": action.count,
            **(
                {"counterpartyPlayerId": action.counterparty_player_id}
                if action.counterparty_player_id is not None
                else {}
            ),
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
    payload: dict[str, object] = {
        "objectiveValue": solution.objective_value,
        "actions": _serialize_solution_actions(solution),
        "shipBuilds": _serialize_solution_ship_builds(solution),
    }
    if solution.ship_first_family is not None:
        payload["shipFirstFamily"] = solution.ship_first_family
    return payload


def _serialize_solution_with_arithmetic(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    solution: InferenceSolution,
    *,
    assign_intervals_to_observed_slack: bool = True,
) -> dict[str, object]:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    payload = _serialize_solution_core(solution)
    payload["militaryScoreArithmetic"] = solution_military_score_arithmetic_payload(
        solution,
        observation,
        actions_by_id,
        combos_by_id,
        assign_intervals_to_observed_slack=assign_intervals_to_observed_slack,
    )
    return payload


def serialize_solution_without_arithmetic(solution: InferenceSolution) -> dict[str, object]:
    return _serialize_solution_core(solution)


def serialize_solutions_with_arithmetic(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    solutions: list[InferenceSolution] | tuple[InferenceSolution, ...],
) -> list[dict[str, object]]:
    """Rank and serialize held top-K rows for NDJSON solution events."""
    ranked = sorted(solutions, key=lambda solution: solution.objective_value, reverse=True)
    return [
        _serialize_solution_with_arithmetic(observation, catalog, solution) for solution in ranked
    ]


def _optional_wire_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _wire_int_default_zero(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def inference_wire_ship_build_entries(solution: dict[str, object]) -> list[dict[str, object]]:
    """Return inference wire ship build objects from one held solution payload."""
    raw = solution.get("shipBuilds")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def inference_wire_solution_objective_value(solution: dict[str, object]) -> int:
    """Return the objective rank weight from one inference wire solution payload."""
    objective = solution.get("objectiveValue", 0)
    if isinstance(objective, bool) or not isinstance(objective, (int, float)):
        return 0
    return int(objective)


def inference_solution_ship_build_from_wire(
    data: dict[str, Any],
) -> InferenceSolutionShipBuild | None:
    """Deserialize one inference wire ship build entry into a domain ship build."""
    count = data.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return None

    combo_id_raw = data.get("comboId")
    combo_id = "" if combo_id_raw is None else str(combo_id_raw)

    label = data.get("label", "")
    if not isinstance(label, str):
        label = str(label)

    return InferenceSolutionShipBuild(
        combo_id=combo_id,
        label=label,
        count=count,
        hull_id=_optional_wire_int(data.get("hullId")),
        engine_id=_optional_wire_int(data.get("engineId")),
        beam_id=_optional_wire_int(data.get("beamId")),
        torp_id=_optional_wire_int(data.get("torpId")),
        beam_count=_wire_int_default_zero(data.get("beamCount")),
        launcher_count=_wire_int_default_zero(data.get("launcherCount")),
    )
