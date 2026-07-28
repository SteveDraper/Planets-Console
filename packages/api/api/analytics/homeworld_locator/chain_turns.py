"""Ensure contiguous TurnInfo storage for homeworld evidence-chain walks."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_dependency_walk import ensure_dependency_turn_floor
from api.analytics.export_types import ExportScope
from api.analytics.homeworld_locator.compute_services import HomeworldLocatorComputeServices


@dataclass(frozen=True)
class HomeworldChainTurnFillResult:
    """Outcome of attempting to auto-fetch missing turns on the ensure path."""

    fetched_turns: tuple[int, ...]
    """Turn numbers successfully loaded via ``ensure_turn`` in this attempt."""
    still_missing: int | None
    """First turn still absent after the attempt (None when the chain is contiguous)."""
    auto_fetch_unavailable: bool
    """True when ``ensure_turn`` is not wired (no login / credential for turn load)."""


def missing_homeworld_chain_turns(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> tuple[int, ...]:
    """Return missing turn numbers on ``[ensure_floor, shell)`` ascending."""
    floor = ensure_dependency_turn_floor(ctx, scope)
    missing: list[int] = []
    for turn_number in range(floor, scope.turn):
        if ctx.load_turn(turn_number) is None:
            missing.append(turn_number)
    return tuple(missing)


def fill_missing_homeworld_chain_turns(
    services: HomeworldLocatorComputeServices,
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> HomeworldChainTurnFillResult:
    """Auto-fetch missing intermediate turns via ``services.ensure_turn``.

    The evidence self-chain requires contiguous stored turns from the accelerated
    ensure floor through ``scope.turn - 1``. When a login-backed ``ensure_turn``
    hook is present, fetch each hole from Planets.nu into storage before the
    export walk continues. Stops at the first fetch failure.
    """
    missing = missing_homeworld_chain_turns(ctx, scope)
    if not missing:
        return HomeworldChainTurnFillResult(
            fetched_turns=(),
            still_missing=None,
            auto_fetch_unavailable=False,
        )
    if services.ensure_turn is None:
        return HomeworldChainTurnFillResult(
            fetched_turns=(),
            still_missing=missing[0],
            auto_fetch_unavailable=True,
        )

    fetched: list[int] = []
    for turn_number in missing:
        ensured = services.ensure_turn(turn_number)
        if ensured is None or ctx.load_turn(turn_number) is None:
            return HomeworldChainTurnFillResult(
                fetched_turns=tuple(fetched),
                still_missing=turn_number,
                auto_fetch_unavailable=False,
            )
        fetched.append(turn_number)
    return HomeworldChainTurnFillResult(
        fetched_turns=tuple(fetched),
        still_missing=None,
        auto_fetch_unavailable=False,
    )
