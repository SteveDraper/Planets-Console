"""BFF Scores table analytic handler."""

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


def _inference_cell_display_status(inference: dict[str, object]) -> str:
    status = str(inference.get("status", ""))
    solution_count = inference.get("solutionCount", 0)
    if status == "exact":
        return "success"
    if status == "time_limited" and isinstance(solution_count, int) and solution_count > 0:
        return "success"
    if status == "time_limited" and inference.get("isComplete") is False:
        return "pending"
    return "failure"


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
    if isinstance(player_id, int):
        shaped["playerId"] = player_id
    return shaped


def _pending_inference_stub(player_id: object) -> dict[str, object]:
    stub: dict[str, object] = {}
    if isinstance(player_id, int):
        stub["playerId"] = player_id
    return stub


def table_from_core(core_data: dict, *, include_build_inference: bool = False) -> dict:
    columns = list(TABLE_COLUMNS)
    if include_build_inference:
        columns.append(INFERENCE_COLUMN)

    rows: list[list[str]] = []
    inference_by_row: list[dict[str, object]] = []
    for row in core_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        table_row = [
            str(row.get("racePlayer", "")),
            *[_format_score_cell(row.get(field)) for field in TABLE_FIELDS],
        ]
        if include_build_inference:
            inference_by_row.append(_pending_inference_stub(row.get("playerId")))
        rows.append(table_row)

    payload: dict[str, object] = {
        "analyticId": ANALYTIC_ID,
        "columns": columns,
        "rows": rows,
    }
    if include_build_inference:
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


DESCRIPTOR = AnalyticDescriptor(
    id=ANALYTIC_ID,
    name="Scores",
    supports_table=True,
    supports_map=False,
    type="selectable",
    get_table=get_table,
)
