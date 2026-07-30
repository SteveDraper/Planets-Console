"""Auto-fill missing TurnInfo below an export ensure scope.

Self-chained analytics (``EnsureDependency`` on themselves at ``turn_delta=-1``)
need contiguous stored turns from the ensure floor through the shell turn. This
helper is the shared fill policy analytics opt into when the dependency walk
reports a hole; the framework still owns the ensure loop itself
(``AnalyticQueryContext.ensure_declared_dependencies``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_dependency_walk import ensure_dependency_turn_floor
from api.analytics.export_types import ExportScope
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


@dataclass(frozen=True)
class DependencyChainTurnFill:
    """Outcome of one attempt to auto-fetch missing turns below an ensure scope."""

    fetched_turns: tuple[int, ...]
    """Turn numbers successfully loaded via ``ensure_turn`` in this attempt."""
    still_missing: int | None
    """First turn still absent after the attempt (None when the chain is contiguous)."""
    auto_fetch_unavailable: bool
    """True when no ``ensure_turn`` hook is wired (no login / credential for turn load)."""


def missing_dependency_chain_turns(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> tuple[int, ...]:
    """Return missing turn numbers on ``[ensure floor, scope.turn)`` ascending."""
    floor = ensure_dependency_turn_floor(ctx, scope)
    return tuple(
        turn_number
        for turn_number in range(floor, scope.turn)
        if ctx.load_turn(turn_number) is None
    )


def fill_missing_dependency_chain_turns(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    ensure_turn: Callable[[int], TurnInfo | None] | None,
) -> DependencyChainTurnFill:
    """Auto-fetch each missing turn below ``scope.turn`` via ``ensure_turn``.

    When a login-backed ``ensure_turn`` hook is present, fetch every hole from
    Planets.nu into storage so the ensure walk can continue. Stops at the first
    fetch failure.
    """
    missing = missing_dependency_chain_turns(ctx, scope)
    if not missing:
        return DependencyChainTurnFill(
            fetched_turns=(),
            still_missing=None,
            auto_fetch_unavailable=False,
        )
    if ensure_turn is None:
        return DependencyChainTurnFill(
            fetched_turns=(),
            still_missing=missing[0],
            auto_fetch_unavailable=True,
        )

    fetched: list[int] = []
    for turn_number in missing:
        if ensure_turn(turn_number) is None or ctx.load_turn(turn_number) is None:
            return DependencyChainTurnFill(
                fetched_turns=tuple(fetched),
                still_missing=turn_number,
                auto_fetch_unavailable=False,
            )
        fetched.append(turn_number)
    return DependencyChainTurnFill(
        fetched_turns=tuple(fetched),
        still_missing=None,
        auto_fetch_unavailable=False,
    )
