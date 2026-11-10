"""Submit on-walks for live fleet and scoreboard streams when the setting turns on.

A turn with no live stream stays quiet. Each stream submits only the players
it was opened for, and never a player eliminated on its turn: that player has
no walk, so nothing is submitted and no work_accepted reaches the row. One
player does not wait for another.
A player who still has a non-terminal fleet or scoreboard node from an
off-setting walk is submitted after that node completes, and only while the
setting is still on and that stream is still live. The follow-up is a
``force_fresh`` submit after the orchestrator has released its lock. A failed
off-setting node is terminal for the wait. A running off-setting scoreboard
does not absorb the on-walk by attach. Streams are not re-admitted, so stored
rows do not return to turn load.

Each player's submits run on that player's own background thread, off the
thread that turned the setting on and off the orchestrator listener that saw
the blocker finish. A submit may fetch missing earlier turns from Planets.nu
before it plans the walk, so one player's slow fetch does not hold another
player's submit, the settings write, or the listener. A shell whose submit
raises is logged and skipped, so one player's failure does not stop the
others. The setting stays stored: a stream attached while the setting is on
submits its own on-walk.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import NamedTuple, Protocol, runtime_checkable

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.eliminated_player import player_has_on_walk_root
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.orchestrator_state import ComputeRequest
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.models.game import TurnInfo
from api.streaming.table_stream.controller_base import WorkAcceptedSink
from api.streaming.table_stream.registry_catalog import LiveTableStream, live_table_streams

logger = logging.getLogger(__name__)


class _PlayerKey(NamedTuple):
    game_id: int
    perspective: int
    player_id: int

    @classmethod
    def of(cls, scope: ComputeScope) -> _PlayerKey:
        return cls(scope.game_id, scope.perspective, scope.player_id)


@runtime_checkable
class _OnWalkStreamController(WorkAcceptedSink, Protocol):
    """What a live fleet or scoreboard stream controller offers an on-walk."""

    turn: TurnInfo
    player_ids: tuple[int, ...]
    query_context: AnalyticQueryContext | None


@dataclass(frozen=True)
class _LiveShell:
    """One player's on-walk root on one live stream."""

    compute_scope: ComputeScope
    ctx: AnalyticQueryContext
    stream: LiveTableStream
    work_accepted_sink: WorkAcceptedSink

    def emit_accepted(self) -> None:
        self.work_accepted_sink.emit_work_accepted(self.compute_scope.player_id)


def submit_on_walks_for_live_streams(
    game_id: int,
    *,
    orchestrator: ComputeOrchestrator | None = None,
) -> list[Future[None]]:
    """Start one on-walk per roster player on each live fleet or scoreboard stream.

    Returns without waiting for any submit, with one future per player that
    resolves once that player's shells have been submitted or skipped. A
    player waiting on an off-setting walk shares the pending waiter's future.
    No live stream does not create an orchestrator. Homeworld streams are not
    scanned.
    """
    shells = _live_shells(game_id)
    if not shells:
        return []
    orch = orchestrator if orchestrator is not None else get_compute_orchestrator()
    by_player: dict[_PlayerKey, list[_LiveShell]] = {}
    for shell in shells:
        by_player.setdefault(_PlayerKey.of(shell.compute_scope), []).append(shell)
    submitted: list[Future[None]] = []
    for player, player_shells in by_player.items():
        if _has_off_setting_walk(orch, player):
            submitted.append(orch.attachment(_PendingOnWalks).wait(orch, player, player_shells))
        else:
            player_submitted: Future[None] = Future()
            _start_submit(orch, player, player_shells, player_submitted)
            submitted.append(player_submitted)
    return submitted


class _PendingOnWalks:
    """One orchestrator's pending off-setting waiters, at most one per player.

    Held through ``ComputeOrchestrator.attachment``, so a waiter whose blocker
    never becomes terminal lives no longer than its orchestrator.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.waiters: dict[_PlayerKey, _OffSettingWalkWaiter] = {}

    def wait(
        self,
        orchestrator: ComputeOrchestrator,
        player: _PlayerKey,
        shells: list[_LiveShell],
    ) -> Future[None]:
        """Submit ``shells`` once the player's off-setting nodes are terminal.

        A later wait for a pending player replaces the shells that waiter
        submits and returns that waiter's future.
        """
        with self.lock:
            pending = self.waiters.get(player)
            if pending is not None:
                pending.shells = shells
                return pending.submitted
            waiter = _OffSettingWalkWaiter(self, orchestrator, player, shells)
            self.waiters[player] = waiter
        waiter.start()
        return waiter.submitted


class _OffSettingWalkWaiter:
    """Submits one player's shells once that player's off-setting nodes are terminal.

    A blocker that clears starts one background submit of each live shell, and
    ``submitted`` resolves when it ends. The pending entry is removed when the
    waiter finishes, and its listener is unregistered.

    The listener is registered before the first check, and the listener and
    that check share one ``_try_finish``, so a node that completes in between
    is submitted once. A parked node stays a blocker. A failed node is
    terminal. A non-terminal off-setting scoreboard is a blocker, so the
    on-walk is not attached to the node that walk opened.
    """

    def __init__(
        self,
        pending: _PendingOnWalks,
        orchestrator: ComputeOrchestrator,
        player: _PlayerKey,
        shells: list[_LiveShell],
    ) -> None:
        self._pending = pending
        self._orchestrator = orchestrator
        self._player = player
        self.shells = shells
        self.submitted: Future[None] = Future()
        self._unregister: Callable[[], None] | None = None

    def start(self) -> None:
        unregister = self._orchestrator.observers.register_scope_outcome_listener(self._on_outcome)
        with self._pending.lock:
            self._unregister = unregister
            is_pending = self._is_pending_locked()
        if not is_pending:
            unregister()
            return
        self._try_finish()

    def _is_pending_locked(self) -> bool:
        return self._pending.waiters.get(self._player) is self

    def _on_outcome(self, snapshot: ScopeLifecycleSnapshot) -> None:
        if (
            snapshot.state in {"complete", "failed"}
            and snapshot.scope.analytic_id in FLEET_WALK_ANALYTIC_IDS
            and _PlayerKey.of(snapshot.scope) == self._player
        ):
            self._try_finish()

    def _try_finish(self) -> None:
        if _has_off_setting_walk(self._orchestrator, self._player):
            return
        with self._pending.lock:
            if not self._is_pending_locked():
                return
            del self._pending.waiters[self._player]
            shells = self.shells
            unregister = self._unregister
        if unregister is not None:
            unregister()
        _start_submit(self._orchestrator, self._player, shells, self.submitted)


def _start_submit(
    orchestrator: ComputeOrchestrator,
    player: _PlayerKey,
    shells: list[_LiveShell],
    submitted: Future[None],
) -> None:
    """Submit one player's ``shells`` on a new thread and resolve ``submitted`` when done."""

    def run() -> None:
        try:
            _submit_shells(orchestrator, shells)
        except Exception as exc:
            logger.exception(
                "On-walk submits failed for game %s perspective %s player %s",
                player.game_id,
                player.perspective,
                player.player_id,
            )
            submitted.set_exception(exc)
            return
        submitted.set_result(None)

    threading.Thread(
        target=run,
        name=f"on-walk-submit-{player.game_id}-{player.perspective}-{player.player_id}",
        daemon=True,
    ).start()


def _submit_shells(orchestrator: ComputeOrchestrator, shells: list[_LiveShell]) -> None:
    for shell in shells:
        if not shell.stream.is_live():
            continue
        if not shell.ctx.backfill_earlier_turns_enabled():
            continue
        try:
            orchestrator.submit(
                ComputeRequest(
                    scope=shell.compute_scope,
                    priority_band="stream_attached",
                    force_fresh=True,
                    ctx=shell.ctx,
                )
            )
        except Exception:
            scope = shell.compute_scope
            logger.exception(
                "On-walk submit failed for game %s perspective %s turn %s player %s (%s)",
                scope.game_id,
                scope.perspective,
                scope.turn,
                scope.player_id,
                scope.analytic_id,
            )
            continue
        shell.emit_accepted()


def _has_off_setting_walk(orchestrator: ComputeOrchestrator, player: _PlayerKey) -> bool:
    """Whether the player has a non-terminal fleet or scores node opened with the setting off."""
    return any(
        not submission_open.backfill_earlier_turns
        for submission_open in orchestrator.non_terminal_submission_opens_for_player(
            game_id=player.game_id,
            perspective=player.perspective,
            player_id=player.player_id,
            analytic_ids=FLEET_WALK_ANALYTIC_IDS,
        )
    )


def _live_shells(game_id: int) -> list[_LiveShell]:
    shells: list[_LiveShell] = []
    for stream in live_table_streams(FLEET_WALK_ANALYTIC_IDS):
        scope = stream.scope
        controller = stream.controller
        if scope.game_id != game_id or not isinstance(scope.perspective, int):
            continue
        if not isinstance(controller, _OnWalkStreamController):
            continue
        ctx = controller.query_context
        if not isinstance(ctx, AnalyticQueryContext):
            continue
        shells.extend(
            _LiveShell(
                compute_scope=ComputeScope(
                    analytic_id=stream.analytic_id,
                    game_id=game_id,
                    perspective=scope.perspective,
                    turn=scope.turn_number,
                    player_id=player_id,
                ),
                ctx=ctx,
                stream=stream,
                work_accepted_sink=controller,
            )
            for player_id in controller.player_ids
            if player_has_on_walk_root(controller.turn, player_id)
        )
    return shells
