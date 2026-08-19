"""Auto-fill missing TurnInfo below an export ensure scope.

Self-chained analytics (``EnsureDependency`` on themselves at ``turn_delta=-1``)
need contiguous stored turns from the ensure floor through the shell turn. This
helper is the shared fill policy when the dependency walk reports a hole.
Orchestrator ``submit`` / ``ensure_scopes`` call :func:`prepare_dependency_chain_turns`
**before** acquiring the orchestrator lock so loadturn I/O never runs under that lock.
``plan_compute_dag`` only walks already-stored turns.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_dependency_walk import ensure_dependency_turn_floor
from api.analytics.export_types import ExportScope, UnavailableReason
from api.errors import ValidationError
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


class DependencyChainFillError(ValidationError):
    """A compute DAG cannot be planned because a required turn is still missing."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        missing_turn: int | None = None,
        fetched_turns: tuple[int, ...] = (),
        auto_fetch_unavailable: bool = False,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.missing_turn = missing_turn
        self.fetched_turns = fetched_turns
        self.auto_fetch_unavailable = auto_fetch_unavailable


def _ensure_turn_hook(
    ctx: AnalyticQueryContext,
    ensure_turn: Callable[[int], TurnInfo | None] | None,
) -> Callable[[int], TurnInfo | None] | None:
    if ensure_turn is not None:
        return ensure_turn
    return ctx.ensure_turn


def _fill_error(scope: ExportScope, fill: DependencyChainTurnFill) -> DependencyChainFillError:
    missing_turn = fill.still_missing
    if fill.auto_fetch_unavailable:
        return DependencyChainFillError(
            (
                f"cannot plan compute DAG: turn {missing_turn} is not stored "
                f"(sign in to auto-fetch missing turns for the evidence chain)"
            ),
            reason="turn_not_stored",
            missing_turn=missing_turn,
            fetched_turns=fill.fetched_turns,
            auto_fetch_unavailable=True,
        )
    message = (
        f"cannot plan compute DAG: could not load turn {missing_turn} from Planets.nu "
        f"(required for the evidence chain"
    )
    if fill.fetched_turns:
        fetched = ",".join(str(turn_number) for turn_number in fill.fetched_turns)
        message += f"; auto-fetched turns {fetched} before failure"
    message += ")"
    return DependencyChainFillError(
        message,
        reason="turn_fetch_failed",
        missing_turn=missing_turn,
        fetched_turns=fill.fetched_turns,
        auto_fetch_unavailable=False,
    )


def _walk_unavailable_error(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    reason: UnavailableReason,
) -> DependencyChainFillError:
    missing_turn: int | None = None
    if reason == "turn_not_stored":
        missing = missing_dependency_chain_turns(ctx, scope)
        missing_turn = missing[0] if missing else None
        if missing_turn is not None:
            message = (
                f"cannot plan compute DAG: turn {missing_turn} is not stored "
                f"(evidence chain requires contiguous turns)"
            )
        else:
            message = (
                "cannot plan compute DAG: an intermediate turn in the evidence chain is not stored"
            )
    else:
        message = f"cannot plan compute DAG: turn unavailable ({reason})"
    return DependencyChainFillError(
        message,
        reason=reason,
        missing_turn=missing_turn,
    )


def prepare_dependency_chain_turns(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    *,
    ensure_turn: Callable[[int], TurnInfo | None] | None = None,
) -> None:
    """Fill missing turns on the ensure chain, or raise ``DependencyChainFillError``.

    No-op when the dependency walk can already complete. Login-backed
    ``ensure_turn`` (argument or ``ctx.ensure_turn``) fetches holes from
    Planets.nu into storage. Callers that plan a compute DAG must invoke this
    **before** ``plan_compute_dag`` and **outside** the orchestrator lock.
    """
    unavailable = ctx.dependency_walk_unavailable(analytic_id, scope)
    if unavailable is None:
        return
    if unavailable == "turn_not_stored":
        fill = fill_missing_dependency_chain_turns(
            ctx,
            scope,
            ensure_turn=_ensure_turn_hook(ctx, ensure_turn),
        )
        if fill.still_missing is not None:
            raise _fill_error(scope, fill)
        unavailable = ctx.dependency_walk_unavailable(analytic_id, scope)
        if unavailable is None:
            return
    raise _walk_unavailable_error(ctx, scope, unavailable)
