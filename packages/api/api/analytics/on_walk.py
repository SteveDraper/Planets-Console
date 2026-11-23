"""On-walk mark and stamp membership for Backfill earlier turns.

Fleet and scoreboard registrations open :func:`open_on_walk_root_plan` around
each submission. While an on-walk shell plans, an absent evidence mark reads
as generation 1 at the ensure baseline, so ensure-final is classified against
the mark the walk will establish. The shell marks its submission open as an
on-walk, so every node the walk plans, and every hop resubmitted from those
nodes, carries that membership. Nothing is written for a join or an empty
plan. A plan that schedules turns establishes that mark and widens
``appliesFromTurn`` backward only, before the first persist. A scoreboard
persist whose producing execution was on the walk stamps and does not bump.
The scores ``tier_solve`` job wire carries that membership as ``onWalk`` onto
the persist payload, so it is the membership at admission, not the live
node's. A scoreboard persist produced off any walk keeps the ordinary bump.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.eliminated_player import player_has_on_walk_root
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.fleet.types import FleetEvidenceMark
from api.compute.dag import PlannedComputeNode, earliest_planned_turn
from api.compute.root_plan import IgnoredRootPlan, RootPlan
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor


@dataclass(frozen=True)
class _OnWalkShell:
    """A fleet or scoreboard shell submitted with Backfill earlier turns on."""

    services: FleetComputeServices
    submission_open: SubmissionOpen
    game_id: int
    perspective: int
    player_id: int
    baseline_mark: FleetEvidenceMark

    def accept_plan(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        """Establish and widen the mark from the plan, before it is registered.

        An empty plan writes nothing. An absent mark becomes generation 1 at
        the ensure baseline. ``appliesFromTurn`` moves backward only, to the
        earliest planned turn. Runs under the orchestrator lock that then
        registers the plan, so no walk node exists before the mark is stored.
        If storing the mark raises, the walk is not registered.
        """
        earliest_turn = earliest_planned_turn(planned)
        if earliest_turn is None:
            return

        def establish_and_widen(current: FleetEvidenceMark) -> FleetEvidenceMark:
            established = self.baseline_mark if current.is_absent else current
            return established.widened_to(earliest_turn)

        self.services.persistence.update_evidence_mark(
            self.game_id,
            self.perspective,
            self.player_id,
            establish_and_widen,
        )


@contextmanager
def open_on_walk_root_plan(
    scope: ComputeScope,
    submission_open: SubmissionOpen,
    ctx: AnalyticQueryContext,
) -> Iterator[RootPlan]:
    """Root-plan hook for fleet and scoreboard shells.

    An on-walk shell plans against generation 1 at the ensure baseline while
    no mark is stored, so a generation-0 ledger is behind the mark and stays
    on the walk. Any other submission is ignored. A player eliminated on the
    shell turn is not an on-walk.
    """
    shell = _on_walk_shell(scope, submission_open, ctx)
    if shell is None:
        yield IgnoredRootPlan(submission_open)
        return
    with shell.services.persistence.assuming_evidence_mark(
        shell.game_id,
        shell.perspective,
        shell.player_id,
        shell.baseline_mark,
    ):
        yield shell


def _on_walk_shell(
    scope: ComputeScope,
    submission_open: SubmissionOpen,
    ctx: AnalyticQueryContext,
) -> _OnWalkShell | None:
    """The on-walk shell this submission opens, or None."""
    if not submission_open.backfill_earlier_turns:
        return None
    open_turn = submission_open.open_turn
    if not isinstance(scope.player_id, int) or not isinstance(scope.perspective, int):
        return None
    if not isinstance(scope.turn, int) or open_turn is None or scope.turn != open_turn:
        return None
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return None
    shell = ctx.load_turn(open_turn)
    if shell is None or not player_has_on_walk_root(shell, scope.player_id):
        return None
    return _OnWalkShell(
        services=services,
        submission_open=replace(submission_open, on_walk=True),
        game_id=scope.game_id,
        perspective=scope.perspective,
        player_id=scope.player_id,
        baseline_mark=FleetEvidenceMark.first_at(
            accelerated_ensure_floor(shell.settings, open_turn)
        ),
    )
