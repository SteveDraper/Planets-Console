"""In-memory persistence for export framework fixture analytics."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.analytics.export_types import ExportScope


@dataclass
class FixtureExportState:
    """Tracks ensure/materialize calls and persisted scopes for tests."""

    persisted: set[tuple[str, ExportScope]] = field(default_factory=set)
    in_flight: set[tuple[str, ExportScope]] = field(default_factory=set)
    ensure_calls: list[tuple[str, ExportScope]] = field(default_factory=list)
    materialize_calls: list[tuple[str, ExportScope]] = field(default_factory=list)
    cycle_on_materialize: bool = False

    def mark_persisted(self, analytic_id: str, scope: ExportScope) -> None:
        self.persisted.add((analytic_id, scope))
        self.in_flight.discard((analytic_id, scope))

    def mark_in_progress(self, analytic_id: str, scope: ExportScope) -> None:
        self.in_flight.add((analytic_id, scope))

    def is_persisted(self, analytic_id: str, scope: ExportScope) -> bool:
        return (analytic_id, scope) in self.persisted

    def is_in_progress(self, analytic_id: str, scope: ExportScope) -> bool:
        return (analytic_id, scope) in self.in_flight

    def reset(self) -> None:
        self.persisted.clear()
        self.in_flight.clear()
        self.ensure_calls.clear()
        self.materialize_calls.clear()
        self.cycle_on_materialize = False


FIXTURE_EXPORT_STATE = FixtureExportState()
