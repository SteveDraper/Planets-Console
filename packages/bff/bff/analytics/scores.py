"""BFF Scores table analytic handler."""

from bff.analytics.models import CoreAnalyticsLoader, TurnScope, load_core_analytic

ANALYTIC_ID = "scores"

METADATA = {
    "id": ANALYTIC_ID,
    "name": "Scores",
    "supportsTable": True,
    "supportsMap": False,
    "type": "selectable",
}

TABLE_COLUMNS = [
    "Race (player)",
    "Planets",
    "Starbases",
    "War Ships",
    "Freighters",
    "Military",
    "Priority Points",
]

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


def table_from_core(core_data: dict) -> dict:
    rows = []
    for row in core_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        rows.append(
            [
                str(row.get("racePlayer", "")),
                *[_format_score_cell(row.get(field)) for field in TABLE_FIELDS],
            ]
        )
    return {
        "analyticId": ANALYTIC_ID,
        "columns": TABLE_COLUMNS,
        "rows": rows,
    }


def get_table(scope: TurnScope, load_core: CoreAnalyticsLoader) -> dict:
    core_data = load_core_analytic(load_core, scope, ANALYTIC_ID)
    return table_from_core(core_data)
