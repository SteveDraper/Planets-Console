"""BFF Scores table analytic handler."""

from collections.abc import Iterator

from api.analytics.catalog import catalog_entry
from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import CoreAnalyticsLoader, TurnScope, load_core_analytic

ANALYTIC_ID = "scores"

TABLE_COLUMNS = [
    "Race (player)",
    "Planets",
    "Starbases",
    "War Ships",
    "Freighters",
    "Military",
    "Priority Points",
]

INFERENCE_COLUMN = "Build inference"

TABLE_FIELDS = [
    "planets",
    "starbases",
    "warShips",
    "freighters",
    "military",
    "priorityPoints",
]


def _format_score_cell(cell: object) -> str:
    if not isinstance(cell, dict):
        return str(cell)
    value = cell.get("value")
    change = cell.get("change")
    if change in (None, 0):
        return str(value)
    if isinstance(change, (int, float)):
        return f"{value} ({change:+g})"
    return f"{value} ({change})"


# Display mapping only -- not Core skip predicates. Unknown terminals stay failure.
INFERENCE_SKIP_DISPLAY_STATUSES = frozenset(
    {
        "viewpoint_owner",
        "dead",
        "full_alliance",
        "horwasp",
        "no_prior_turn",
        "player_not_found",
    }
)


def _inference_cell_display_status(inference: dict[str, object]) -> str:
    status = str(inference.get("status", ""))
    solution_count = inference.get("solutionCount", 0)
    is_complete = inference.get("isComplete", True)
    has_held_solutions = isinstance(solution_count, int) and solution_count > 0

    if status == "paused":
        return "paused"
    if status == "stopped":
        return "success" if has_held_solutions else "stopped"
    if status == "moderate_residual":
        return "moderate_residual"
    if status == "mine_score_residual":
        return "mine_score_residual"
    if status in INFERENCE_SKIP_DISPLAY_STATUSES:
        return "skipped"
    if status == "exact":
        return "success"
    if has_held_solutions and not is_complete:
        return "success"
    # Held time_limited matches stopped-with-solutions: show the count, not stop chrome.
    if status == "time_limited" and has_held_solutions:
        return "success"
    if status == "time_limited" and is_complete is False:
        return "pending"
    if status == "pending" or (not is_complete and not has_held_solutions):
        return "pending"
    return "failure"


def stamp_inference_stream_display_status(
    events: Iterator[dict[str, object]],
) -> Iterator[dict[str, object]]:
    """Stamp BFF ``displayStatus`` on Core ``complete`` stream lines."""
    for event in events:
        if event.get("type") == "complete":
            yield {**event, "displayStatus": _inference_cell_display_status(event)}
        else:
            yield event


def _shape_inference_detail(
    inference: object,
    *,
    player_id: object = None,
) -> dict[str, object]:
    if not isinstance(inference, dict):
        shaped = {
            "displayStatus": "failure",
            "status": "missing_inference",
            "summary": "Inference data unavailable",
            "solutionCount": 0,
            "isComplete": True,
            "solutions": [],
            "diagnostics": {},
        }
    else:
        shaped = {
            "displayStatus": _inference_cell_display_status(inference),
            "status": inference.get("status"),
            "summary": inference.get("summary", ""),
            "solutionCount": inference.get("solutionCount", 0),
            "isComplete": inference.get("isComplete", True),
            "solutions": inference.get("solutions", []),
            "diagnostics": inference.get("diagnostics", {}),
        }
        leftover = inference.get("unexplainedMilitaryDelta2x")
        if isinstance(leftover, int) and not isinstance(leftover, bool):
            shaped["unexplainedMilitaryDelta2x"] = leftover
        placeholders = inference.get("placeholders")
        if isinstance(placeholders, list):
            shaped["placeholders"] = [entry for entry in placeholders if isinstance(entry, dict)]
        fleet_torp_input_status = inference.get("fleetTorpInputStatus")
        if isinstance(fleet_torp_input_status, str):
            shaped["fleetTorpInputStatus"] = fleet_torp_input_status
        belief_set_torp_ids = inference.get("fleetTorpOverlayBeliefSetTorpIds")
        if isinstance(belief_set_torp_ids, list):
            shaped["fleetTorpOverlayBeliefSetTorpIds"] = [
                torp_id for torp_id in belief_set_torp_ids if isinstance(torp_id, int)
            ]
    if isinstance(player_id, int):
        shaped["playerId"] = player_id
    return shaped


def _pending_inference_stub(player_id: object) -> dict[str, object]:
    stub: dict[str, object] = {}
    if isinstance(player_id, int):
        stub["playerId"] = player_id
    return stub


def table_from_core(core_data: dict, *, include_build_inference: bool = False) -> dict:
    available = bool(core_data.get("buildInferenceAvailable", True))
    effective_include = include_build_inference and available
    columns = list(TABLE_COLUMNS)
    if effective_include:
        columns.append(INFERENCE_COLUMN)

    rows: list[list[str]] = []
    row_player_ids: list[int | None] = []
    inference_by_row: list[dict[str, object]] = []
    for row in core_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        player_id = row.get("playerId")
        table_row = [
            str(row.get("racePlayer", "")),
            *[_format_score_cell(row.get(field)) for field in TABLE_FIELDS],
        ]
        if effective_include:
            inference_by_row.append(_pending_inference_stub(player_id))
        rows.append(table_row)
        row_player_ids.append(player_id if isinstance(player_id, int) else None)

    payload: dict[str, object] = {
        "analyticId": ANALYTIC_ID,
        "columns": columns,
        "rows": rows,
        "rowPlayerIds": row_player_ids,
    }
    if "buildInferenceAvailable" in core_data:
        payload["buildInferenceAvailable"] = bool(core_data["buildInferenceAvailable"])
    if include_build_inference and available:
        payload["includeBuildInference"] = True
        payload["inferenceByRow"] = inference_by_row
    return payload


def get_table(
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
    *,
    include_build_inference: bool = False,
) -> dict:
    core_data = load_core_analytic(
        load_core,
        scope,
        ANALYTIC_ID,
        diagnostics=diagnostics,
    )
    return table_from_core(core_data, include_build_inference=include_build_inference)


def inference_from_core(core_inference: object, *, player_id: int) -> dict[str, object]:
    """Shape one Core scores-row inference payload for the SPA."""
    return _shape_inference_detail(core_inference, player_id=player_id)


DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(
    catalog_entry(ANALYTIC_ID),
    get_table=get_table,
)
