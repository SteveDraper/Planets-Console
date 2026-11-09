"""On-walk mark and stamp membership for Backfill earlier turns.

Fleet and scoreboard registrations open :func:`open_on_walk_root_plan` around
each submission. While an on-walk shell plans, an absent evidence mark reads
as generation 1 at the ensure baseline, so ensure-final is classified against
the mark the walk will establish. Nothing is written for a join or an empty
plan. A plan that schedules turns establishes that mark, widens
``appliesFromTurn`` backward only, and remembers the walk, all before the
first persist. Every scoreboard persist that belongs to the walk stamps the
generation the walk started with. A scoreboard persist that belongs to no
in-flight on-walk keeps the ordinary bump.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.eliminated_player import fleet_player_eliminated_at_turn
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.off_mode import mark_is_absent
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.dag import PlannedComputeNode, earliest_planned_turn
from api.compute.root_plan import IGNORED_ROOT_PLAN, RootPlan
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor

_registry_lock = threading.Lock()
_walks: dict[tuple[int, int, int, int], OnWalk] = {}


@dataclass(frozen=True)
class OnWalk:
    """One accepted on-walk for a player, keyed by the shell turn it started at."""

    generation: int
    earliest_turn: int
    open_turn: int


def reset_on_walks_for_tests() -> None:
    """Drop accepted on-walks. Tests that submit with backfill on share this process."""
    with _registry_lock:
        _walks.clear()


@dataclass(frozen=True)
class _OnWalkShell:
    """A fleet or scoreboard shell submitted with Backfill earlier turns on."""

    services: FleetComputeServices
    game_id: int
    perspective: int
    player_id: int
    open_turn: int
    baseline: int

    def plan_registered(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        """Establish and widen the mark from the registered plan, and remember the walk.

        An empty plan writes nothing. An absent mark becomes generation 1 at
        the ensure baseline. ``appliesFromTurn`` moves backward only, to the
        earliest planned turn. Runs outside the orchestrator lock and before
        the first persist.
        """
        earliest_turn = earliest_planned_turn(planned)
        if earliest_turn is None:
            return
        mark = self.services.persistence.update_evidence_mark(
            self.game_id,
            self.perspective,
            self.player_id,
            lambda current: _widen_existing_mark(
                _establish_absent_mark(current, self.baseline),
                earliest_turn,
            ),
        )
        _remember_walk(
            self.game_id,
            self.perspective,
            self.player_id,
            open_turn=self.open_turn,
            generation=mark.evidence_generation,
            earliest_turn=earliest_turn,
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
        yield IGNORED_ROOT_PLAN
        return
    with shell.services.persistence.assuming_evidence_mark(
        shell.game_id,
        shell.perspective,
        shell.player_id,
        FleetEvidenceMark(evidence_generation=1, applies_from_turn=shell.baseline),
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
    if shell is None or fleet_player_eliminated_at_turn(shell, scope.player_id):
        return None
    return _OnWalkShell(
        services=services,
        game_id=scope.game_id,
        perspective=scope.perspective,
        player_id=scope.player_id,
        open_turn=open_turn,
        baseline=accelerated_ensure_floor(shell.settings, open_turn),
    )


def scoreboard_persist_belongs_to_on_walk(
    orchestrator: object,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    host_turn: int,
) -> bool:
    """Whether this scoreboard persist belongs to an in-flight on-walk.

    The producing scores node carries the walk's backfill choice and shell
    turn. Membership is that walk's refresh range. A node accepted while the
    setting was off does not belong to an on-walk.
    """
    reader = getattr(orchestrator, "submission_open_for", None)
    if reader is None:
        return False
    opened = reader(
        ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=game_id,
            perspective=perspective,
            turn=host_turn,
            player_id=player_id,
        )
    )
    if not isinstance(opened, SubmissionOpen):
        return False
    if not opened.backfill_earlier_turns or opened.open_turn is None:
        return False
    walk = _walk_for(game_id, perspective, player_id, opened.open_turn)
    if walk is None:
        return False
    return walk.earliest_turn <= host_turn <= walk.open_turn


def _establish_absent_mark(current: FleetEvidenceMark, baseline: int) -> FleetEvidenceMark:
    if not mark_is_absent(current):
        return current
    return FleetEvidenceMark(evidence_generation=1, applies_from_turn=baseline)


def _widen_existing_mark(current: FleetEvidenceMark, earliest_turn: int) -> FleetEvidenceMark:
    """Move ``appliesFromTurn`` backward to ``earliest_turn``. Never forward."""
    if mark_is_absent(current):
        return current
    applies = current.applies_from_turn
    if applies is not None and earliest_turn >= applies:
        return current
    return FleetEvidenceMark(
        evidence_generation=current.evidence_generation,
        applies_from_turn=earliest_turn,
    )


def _remember_walk(
    game_id: int,
    perspective: int,
    player_id: int,
    *,
    open_turn: int,
    generation: int,
    earliest_turn: int,
) -> None:
    key = (game_id, perspective, player_id, open_turn)
    with _registry_lock:
        existing = _walks.get(key)
        if existing is None:
            _walks[key] = OnWalk(
                generation=generation,
                earliest_turn=earliest_turn,
                open_turn=open_turn,
            )
            return
        earliest = existing.earliest_turn
        if earliest_turn < earliest:
            earliest = earliest_turn
        _walks[key] = OnWalk(
            generation=existing.generation,
            earliest_turn=earliest,
            open_turn=open_turn,
        )


def _walk_for(
    game_id: int,
    perspective: int,
    player_id: int,
    open_turn: int,
) -> OnWalk | None:
    with _registry_lock:
        return _walks.get((game_id, perspective, player_id, open_turn))
