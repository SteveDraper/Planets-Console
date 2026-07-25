"""Resolve homeworld locator services from AnalyticQueryContext."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.errors import ValidationError
from api.models.game import TurnInfo


@dataclass(frozen=True)
class HomeworldLocatorComputeServices:
    """Injected services for homeworld locator ensure and compute."""

    persistence: HomeworldLocatorPersistenceService
    game_id: int
    perspective: int
    load_turn: Callable[[int], TurnInfo | None]
    list_stored_turns: Callable[[], list[int]]
    ensure_turn: Callable[[int], TurnInfo | None] | None = None
    """Optional auto-ensure hook (e.g. turn 1). Returns loaded turn or None on failure."""


def resolve_homeworld_services(ctx: AnalyticQueryContext) -> HomeworldLocatorComputeServices:
    injected = ctx.export_services.get(ANALYTIC_ID)
    if injected is None:
        raise ValidationError(f"Homeworld locator requires {ANALYTIC_ID!r} in ctx.export_services")
    if not isinstance(injected, HomeworldLocatorComputeServices):
        raise ValidationError(
            f"export_services[{ANALYTIC_ID!r}] must be HomeworldLocatorComputeServices, "
            f"got {type(injected).__name__}"
        )
    return injected


def build_ephemeral_homeworld_services(
    *,
    persistence: HomeworldLocatorPersistenceService,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None],
    list_stored_turns: Callable[[], list[int]] | None = None,
    ensure_turn: Callable[[int], TurnInfo | None] | None = None,
) -> HomeworldLocatorComputeServices:
    def _list_stored() -> list[int]:
        if list_stored_turns is not None:
            return list_stored_turns()
        # Fallback: probe common early turns when tests only wire load_turn.
        found: list[int] = []
        for turn_number in range(1, 512):
            if load_turn(turn_number) is not None:
                found.append(turn_number)
            elif found:
                break
        return found

    return HomeworldLocatorComputeServices(
        persistence=persistence,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        list_stored_turns=_list_stored,
        ensure_turn=ensure_turn,
    )
