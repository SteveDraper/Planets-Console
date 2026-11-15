"""What a fleet evidence bump settles, and which live rows it wakes.

A durable bump (a persisted scores row, or a changed hull mask) moves one
player's evidence mark, so that player's in-flight fleet and scoreboard work
must not stamp the old one. :class:`DurableRecompute` watches and wakes only
the player's live fleet and scoreboard rows, under either **Backfill earlier
turns** setting:

- :class:`BumpSettlePolicy` keeps only a running off-walk node on a watched
  turn and aborts everything else. Watched turns are the live-row turns with
  the setting off, and none with it on (:func:`bump_watched_turns`).
- The settle publishes the new mark and epoch in its own lock hold.
- The wake reschedules live rows at the evidence host turn and later, plus each
  live row whose own root the settle stopped. A rescheduled row re-admits with
  its stream's query context, which submits the replacement walk.

Held admission (:class:`HeldRecompute`) settles nothing and wakes every known
fleet turn.

The carried submission choice on an unconsumed root still classifies stamp
versus bump (:func:`resolve_durable_scores_evidence`); it no longer chooses
what wakes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.walk_row_reschedule import has_stopped_scope
from api.analytics.walk_shell_watch import LiveWalkShell, live_walk_shells
from api.compute.in_flight_settle import (
    InFlightCandidate,
    InFlightSettlePolicy,
    RunningDisposition,
    UnstartedDisposition,
)
from api.compute.orchestrator import OpenTurnRoot
from api.compute.scope import ComputeScope
from api.services.in_flight_orchestrator import InFlightOrchestrator


def preferred_unconsumed_root_backfill(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    preferred_analytic_id: str,
) -> bool | None:
    """Backfill choice of the unconsumed root at ``host_turn``.

    None when no such root exists. ``preferred_analytic_id`` wins when more
    than one analytic has an unconsumed root at that turn. When it does not,
    the last other root in scan order supplies the choice.
    """
    found: bool | None = None
    for root in roots:
        if root.consumed or root.open_turn != host_turn:
            continue
        if root.analytic_id == preferred_analytic_id:
            return root.backfill_earlier_turns
        found = root.backfill_earlier_turns
    return found


def claim_player_open_roots(
    orchestrator: InFlightOrchestrator,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    open_turn: int,
) -> tuple[OpenTurnRoot, ...]:
    """In-flight roots, consuming ``open_turn`` when an unconsumed root is there.

    The snapshot is the state from before that consume.
    """
    return orchestrator.claim_open_turn_roots(
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        open_turn=open_turn,
        analytic_ids=FLEET_WALK_ANALYTIC_IDS,
    )


def player_live_walk_rows(
    game_id: int,
    perspective: int,
    player_id: int,
) -> tuple[LiveWalkShell, ...]:
    """The player's live fleet and scoreboard rows in one game and perspective.

    One registry scan of published snapshots; it takes no lock.
    """
    return tuple(
        row
        for row in live_walk_shells()
        if row.key.game_id == game_id
        and row.key.perspective == perspective
        and row.key.player_id == player_id
    )


def bump_watched_turns(
    *,
    backfill_enabled: bool,
    live_rows: Iterable[LiveWalkShell],
) -> frozenset[int]:
    """The turns whose running off-walk work a durable bump keeps.

    With the setting off, the turns of the player's live rows: work there
    still serves an open row and the wake re-admits that row. With the
    setting on, none: every live row submits a new walk.
    """
    if backfill_enabled:
        return frozenset()
    return frozenset(row.key.turn for row in live_rows)


@dataclass(frozen=True)
class BumpSettlePolicy(InFlightSettlePolicy):
    """What a durable bump does to one node of the player's fleet and scoreboard work.

    A running node off the walk on a watched turn is kept. Every other node
    is aborted, so the player's walk always stops and nothing it ran can
    stamp the old mark.
    """

    watched_turns: frozenset[int]

    def unstarted(self, candidate: InFlightCandidate) -> UnstartedDisposition:
        return UnstartedDisposition.ABORT

    def running(self, candidate: InFlightCandidate) -> RunningDisposition:
        if not candidate.submission_open.on_walk and candidate.scope.turn in self.watched_turns:
            return RunningDisposition.KEEP
        return RunningDisposition.ABORT


@dataclass(frozen=True)
class LiveRowWake:
    """Reschedule one live fleet or scoreboard row through its stream."""

    row: LiveWalkShell


@dataclass(frozen=True)
class FleetScopeWake:
    """Wake one fleet scope: its open stream's row, or a ``force_fresh`` submit."""

    scope: ComputeScope


WakeTarget: TypeAlias = LiveRowWake | FleetScopeWake


class BumpRecompute(Protocol):
    """What one bump settles and wakes."""

    def settle_policy(self, live_rows: tuple[LiveWalkShell, ...]) -> InFlightSettlePolicy | None:
        """The policy the bump settles the player's work with, or None to settle nothing."""
        ...

    def wake_targets(
        self,
        *,
        known_turns: frozenset[int],
        stopped: frozenset[ComputeScope],
        live_rows: tuple[LiveWalkShell, ...],
    ) -> tuple[WakeTarget, ...]:
        """What to wake once the bump has published.

        ``known_turns`` are the ledger bump's turns, ``stopped`` the scopes the
        settle stopped, and ``live_rows`` a scan taken after the publish.
        """
        ...


@dataclass(frozen=True)
class DurableRecompute(BumpRecompute):
    """A durable bump from evidence at ``host_turn``: the one live-row rule."""

    host_turn: int
    backfill_enabled: bool

    def settle_policy(self, live_rows: tuple[LiveWalkShell, ...]) -> BumpSettlePolicy:
        return BumpSettlePolicy(
            watched_turns=bump_watched_turns(
                backfill_enabled=self.backfill_enabled, live_rows=live_rows
            )
        )

    def wake_targets(
        self,
        *,
        known_turns: frozenset[int],
        stopped: frozenset[ComputeScope],
        live_rows: tuple[LiveWalkShell, ...],
    ) -> tuple[WakeTarget, ...]:
        """Live rows at ``host_turn`` and later, and live rows whose own root was stopped.

        A known turn with no live row is not woken: it keeps its old generation
        until something opens it.
        """
        return tuple(
            LiveRowWake(row=row)
            for row in live_rows
            if row.key.turn >= self.host_turn or has_stopped_scope(row, stopped)
        )


@dataclass(frozen=True)
class HeldRecompute(BumpRecompute):
    """Held admission: settle nothing and wake every known fleet turn of the player."""

    game_id: int
    perspective: int
    player_id: int

    def settle_policy(self, live_rows: tuple[LiveWalkShell, ...]) -> None:
        return None

    def wake_targets(
        self,
        *,
        known_turns: frozenset[int],
        stopped: frozenset[ComputeScope],
        live_rows: tuple[LiveWalkShell, ...],
    ) -> tuple[WakeTarget, ...]:
        return tuple(
            FleetScopeWake(
                scope=ComputeScope(
                    analytic_id=FLEET_ANALYTIC_ID,
                    game_id=self.game_id,
                    perspective=self.perspective,
                    turn=turn,
                    player_id=self.player_id,
                )
            )
            for turn in sorted(known_turns)
        )


@dataclass(frozen=True)
class DurableScoresEvidence:
    """One durable scores persist, split by which backfill each step uses.

    Stamp versus bump uses the carried submission choice: ``decision_backfill``
    and ``open_turn``. Both are None when this host turn has no unconsumed
    root, and that persist cannot stamp.

    ``wake_backfill`` is the current backfill record. It chooses what a bump
    watches. It does not classify the mark.
    """

    open_turn: int | None
    decision_backfill: bool | None
    wake_backfill: bool


def resolve_durable_scores_evidence(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    wake_backfill: bool,
) -> DurableScoresEvidence:
    """Carried submission choice and the current backfill record.

    ``open_turn`` is set exactly when an unconsumed root at ``host_turn``
    carries a backfill choice. A scores root wins over a fleet root. That is
    also when that root is consumed.
    """
    carried = preferred_unconsumed_root_backfill(
        roots,
        host_turn=host_turn,
        preferred_analytic_id=SCORES_ANALYTIC_ID,
    )
    return DurableScoresEvidence(
        open_turn=None if carried is None else host_turn,
        decision_backfill=carried,
        wake_backfill=wake_backfill,
    )
