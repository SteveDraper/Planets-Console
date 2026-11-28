"""Auto-fill missing TurnInfo below an export ensure scope.

Self-chained analytics (``EnsureDependency`` on themselves at ``turn_delta=-1``)
need contiguous stored turns from the ensure floor through the shell turn. This
helper is the shared fill policy when the dependency walk reports a hole.
``force_root`` must match the subsequent ``plan_compute_dag`` walk so an entry
step still fills prior-turn holes when the cheap walk would treat the root as
satisfied. Orchestrator ``submit`` / ``ensure_scopes`` call
:func:`prepare_dependency_chain_turns` **before** acquiring the orchestrator
lock so loadturn I/O never runs under that lock. ``plan_compute_dag`` only
walks already-stored turns.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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

    The fill bounds turn-fetch nesting:

    - It works out every hole on ``[ensure floor, scope.turn)`` once, then
      fetches them in ascending order from this one frame; the loop here, not
      any nested submit, owns the iteration over missing turns.
    - A nested fill for a lower scope reads the same floor, except at the
      accelerated-start boundary: a scope at turn N-1 (N the first reliable
      scoreboard turn) has floor 1 where scopes at N and above have floor N.
    - A stored turn is never fetched twice: holes are the turns ``ctx.load_turn``
      cannot read, and a fetched turn is stored before its turn-stored hook runs.

    Its single caller is :func:`prepare_dependency_chain_turns`, which the
    compute orchestrator runs while planning a root (``submit`` / ``ensure_scopes``).
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


ChainFillReason = UnavailableReason | Literal["turn_fetch_failed"]
"""Why a chain fill failed: the dependency walk's reason, or a failed turn fetch."""


class DependencyChainFillError(ValidationError):
    """A compute DAG cannot be planned because a required turn is still missing.

    ``detail`` states the failure without a caller's framing; ``str(error)`` is
    ``"cannot plan compute DAG: " + detail``. A caller that reports the failure
    in its own words prefixes ``detail`` instead of rebuilding it.
    """

    def __init__(
        self,
        detail: str,
        *,
        reason: ChainFillReason,
        missing_turn: int | None,
    ) -> None:
        super().__init__(f"cannot plan compute DAG: {detail}")
        self.detail = detail
        self.reason = reason
        self.missing_turn = missing_turn


def _fill_error(fill: DependencyChainTurnFill) -> DependencyChainFillError:
    missing_turn = fill.still_missing
    if fill.auto_fetch_unavailable:
        return DependencyChainFillError(
            (
                f"turn {missing_turn} is not stored "
                f"(sign in to auto-fetch missing turns for the evidence chain)"
            ),
            reason="turn_not_stored",
            missing_turn=missing_turn,
        )
    detail = f"could not load turn {missing_turn} from Planets.nu (required for the evidence chain"
    if fill.fetched_turns:
        fetched = ",".join(str(turn_number) for turn_number in fill.fetched_turns)
        detail += f"; auto-fetched turns {fetched} before failure"
    detail += ")"
    return DependencyChainFillError(
        detail,
        reason="turn_fetch_failed",
        missing_turn=missing_turn,
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
            detail = f"turn {missing_turn} is not stored (evidence chain requires contiguous turns)"
        else:
            detail = "an intermediate turn in the evidence chain is not stored"
    else:
        detail = f"turn unavailable ({reason})"
    return DependencyChainFillError(
        detail,
        reason=reason,
        missing_turn=missing_turn,
    )


def prepare_dependency_chain_turns(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    *,
    force_root: bool = False,
    backfill_earlier_turns: bool,
) -> None:
    """Fill missing turns on the ensure chain, or raise ``DependencyChainFillError``.

    No-op when the dependency walk can already complete. Pass ``force_root`` to
    match ``plan_compute_dag`` so a satisfied root still inspects ``-1`` edges
    (scores RowRun / entry ``step_kind``). Login-backed ``ctx.ensure_turn``
    fetches holes from Planets.nu into storage. Callers that plan a compute DAG
    must invoke this **before** ``plan_compute_dag`` and **outside** the
    orchestrator lock.
    """
    unavailable = ctx.dependency_walk_unavailable(
        analytic_id,
        scope,
        force_root=force_root,
        backfill_earlier_turns=backfill_earlier_turns,
    )
    if unavailable is None:
        return
    if unavailable == "turn_not_stored":
        fill = fill_missing_dependency_chain_turns(
            ctx,
            scope,
            ensure_turn=ctx.ensure_turn,
        )
        if fill.still_missing is not None:
            raise _fill_error(fill)
        unavailable = ctx.dependency_walk_unavailable(
            analytic_id,
            scope,
            force_root=force_root,
            backfill_earlier_turns=backfill_earlier_turns,
        )
        if unavailable is None:
            return
    raise _walk_unavailable_error(ctx, scope, unavailable)
