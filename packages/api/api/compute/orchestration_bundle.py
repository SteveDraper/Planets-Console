"""Leader-retained orchestration-plane inputs for a compute node (#209).

``load_turn`` is not sticky: the process-wide orchestrator turn cache is keyed by
``(game_id, perspective, turn)``. This bundle retains analytic ``export_services``
and the ensure/memo owner (an ``AnalyticQueryContext``) from the submitting leader
until the node is terminal. Process/shell-scoped services are follow-on #239.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from api.analytics.export_context import AnalyticQueryContext
from api.models.game import TurnInfo


@dataclass(frozen=True)
class OrchestrationBundle:
    """Sticky leader inputs for wire build, ensure/materialize, and persist."""

    query_context: AnalyticQueryContext

    @classmethod
    def from_context(cls, ctx: AnalyticQueryContext) -> OrchestrationBundle:
        return cls(query_context=ctx)

    @property
    def export_services(self) -> Mapping[str, object]:
        return self.query_context.export_services

    @property
    def game_id(self) -> int:
        return self.query_context.game_id

    @property
    def perspective(self) -> int:
        return self.query_context.perspective

    @property
    def ambient_turn(self) -> int:
        return self.query_context.ambient_turn

    def query_context_with_load_turn(
        self,
        load_turn: Callable[[int], TurnInfo | None],
    ) -> AnalyticQueryContext:
        """Return a ctx view with orchestration-plane ``load_turn`` substituted."""
        return replace(self.query_context, load_turn=load_turn)
