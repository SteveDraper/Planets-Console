"""Registration descriptor for a BFF turn analytic."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from api.diagnostics import Diagnostics

from bff.analytics.models import ConnectionsMapQuery, CoreAnalyticsLoader, TurnScope

AnalyticType = Literal["base", "selectable"]

TableHandler = Callable[[TurnScope, CoreAnalyticsLoader, Diagnostics], dict]

MapHandler = Callable[
    [TurnScope, ConnectionsMapQuery, CoreAnalyticsLoader, Diagnostics],
    dict,
]

MapDiagnosticValuesHook = Callable[[ConnectionsMapQuery], dict[str, Any]]


@dataclass(frozen=True)
class AnalyticDescriptor:
    """Single registration unit for one turn analytic in the BFF layer."""

    id: str
    name: str
    supports_table: bool
    supports_map: bool
    type: AnalyticType
    get_table: TableHandler | None = None
    get_map: MapHandler | None = None
    map_diagnostic_values: MapDiagnosticValuesHook | None = None
    map_timing_section: str = "turn_analytics_from_core"

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "supportsTable": self.supports_table,
            "supportsMap": self.supports_map,
            "type": self.type,
        }
