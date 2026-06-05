"""Registration descriptor for a BFF turn analytic."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from api.analytics.catalog import AnalyticType, TurnAnalyticCatalogEntry
from api.diagnostics import Diagnostics

from bff.analytics.models import ConnectionsMapQuery, CoreAnalyticsLoader, TurnScope

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

    @classmethod
    def from_catalog_entry(
        cls,
        entry: TurnAnalyticCatalogEntry,
        *,
        get_table: TableHandler | None = None,
        get_map: MapHandler | None = None,
        map_diagnostic_values: MapDiagnosticValuesHook | None = None,
        map_timing_section: str = "turn_analytics_from_core",
    ) -> "AnalyticDescriptor":
        return cls(
            id=entry.id,
            name=entry.name,
            supports_table=entry.supports_table,
            supports_map=entry.supports_map,
            type=entry.type,
            get_table=get_table,
            get_map=get_map,
            map_diagnostic_values=map_diagnostic_values,
            map_timing_section=map_timing_section,
        )
