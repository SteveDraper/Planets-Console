"""Submit on-walks for live fleet and scoreboard streams when the setting turns on.

A turn with no live stream stays quiet. One player does not wait for another.
A player who still has a non-terminal fleet or scoreboard node from an
off-setting walk is submitted after that node completes, and only while the
setting is still on and that stream is still live. The follow-up is a
``force_fresh`` submit after the orchestrator has released its lock. A failed
off-setting node is terminal for the wait. A running off-setting scoreboard
does not absorb the on-walk by attach. Streams are not re-admitted, so stored
rows do not return to turn load.

A shell whose submit raises is logged and skipped, so one player's failure
does not stop the others. The setting stays stored: a stream attached while
the setting is on submits its own on-walk.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.off_mode import FLEET_WALK_ANALYTIC_IDS
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.orchestrator_state import ComputeRequest
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.models.game import TurnInfo
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.registry_catalog import registered_table_stream_registries

logger = logging.getLogger(__name__)


class _LiveStreamController(Protocol):
    """Fleet or inference table stream that can accept an on-walk."""

    @property
    def turn(self) -> TurnInfo: ...

    @property
    def query_context(self) -> AnalyticQueryContext | None: ...

    def emit_work_accepted(self, player_id: int) -> None: ...


class _PlayerKey(NamedTuple):
    game_id: int
    perspective: int
    player_id: int

    @classmethod
    def of(cls, scope: ComputeScope) -> _PlayerKey:
        return cls(scope.game_id, scope.perspective, scope.player_id)


@dataclass(frozen=True)
class _LiveShell:
    """One player's on-walk root on one live stream."""

    compute_scope: ComputeScope
    ctx: AnalyticQueryContext
    registry: TableStreamRegistry[Any, Any]
    stream_scope: Any
    controller: _LiveStreamController

    def still_live(self) -> bool:
        return self.registry.controller_for_scope(self.stream_scope) is not None

    def emit_accepted(self) -> None:
        self.controller.emit_work_accepted(self.compute_scope.player_id)


def submit_on_walks_for_live_streams(
    game_id: int,
    *,
    orchestrator: ComputeOrchestrator | None = None,
) -> None:
    """Submit one on-walk per roster player on each live fleet or scoreboard stream.

    No live stream does not create an orchestrator. Homeworld streams are not
    scanned.
    """
    shells = _live_shells(game_id)
    if not shells:
        return
    orch = orchestrator if orchestrator is not None else get_compute_orchestrator()
    by_player: dict[_PlayerKey, list[_LiveShell]] = {}
    for shell in shells:
        by_player.setdefault(_PlayerKey.of(shell.compute_scope), []).append(shell)
    for player, player_shells in by_player.items():
        if _has_off_setting_walk(orch, player):
            _OffSettingWalkWaiter.wait(orch, player, player_shells)
        else:
            _submit_shells(orch, player_shells)


class _WaiterKey(NamedTuple):
    orchestrator: ComputeOrchestrator
    player: _PlayerKey


class _OffSettingWalkWaiter:
    """Submits one player's shells once that player's off-setting nodes are terminal.

    There is at most one pending waiter per orchestrator and player. A later
    wait for that player replaces the shells the pending waiter submits, so a
    blocker that clears submits each live shell once. The pending entry is
    removed when the waiter finishes, and its listener is unregistered.

    The listener is registered before the first check, and the listener and
    that check share one ``_try_finish``, so a node that completes in between
    is submitted once. A parked node stays a blocker. A failed node is
    terminal. A non-terminal off-setting scoreboard is a blocker, so the
    on-walk is not attached to the node that walk opened.
    """

    _pending_lock = threading.Lock()
    _pending: dict[_WaiterKey, _OffSettingWalkWaiter] = {}

    def __init__(self, key: _WaiterKey, shells: list[_LiveShell]) -> None:
        self._key = key
        self._shells = shells
        self._unregister: Callable[[], None] | None = None

    @classmethod
    def wait(
        cls,
        orchestrator: ComputeOrchestrator,
        player: _PlayerKey,
        shells: list[_LiveShell],
    ) -> None:
        key = _WaiterKey(orchestrator, player)
        with cls._pending_lock:
            pending = cls._pending.get(key)
            if pending is not None:
                pending._shells = shells
                return
            waiter = cls(key, shells)
            cls._pending[key] = waiter
        waiter._start()

    def _start(self) -> None:
        unregister = self._key.orchestrator.observers.register_scope_outcome_listener(
            self._on_outcome
        )
        with self._pending_lock:
            self._unregister = unregister
            is_pending = self._is_pending_locked()
        if not is_pending:
            unregister()
            return
        self._try_finish()

    def _is_pending_locked(self) -> bool:
        return self._pending.get(self._key) is self

    def _on_outcome(self, snapshot: ScopeLifecycleSnapshot) -> None:
        if (
            snapshot.state in {"complete", "failed"}
            and snapshot.scope.analytic_id in FLEET_WALK_ANALYTIC_IDS
            and _PlayerKey.of(snapshot.scope) == self._key.player
        ):
            self._try_finish()

    def _try_finish(self) -> None:
        orchestrator = self._key.orchestrator
        if _has_off_setting_walk(orchestrator, self._key.player):
            return
        with self._pending_lock:
            if not self._is_pending_locked():
                return
            del self._pending[self._key]
            shells = self._shells
            unregister = self._unregister
        if unregister is not None:
            unregister()
        _submit_shells(orchestrator, shells)


def _submit_shells(orchestrator: ComputeOrchestrator, shells: list[_LiveShell]) -> None:
    for shell in shells:
        if not shell.still_live():
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
    for analytic_id, registry in registered_table_stream_registries(FLEET_WALK_ANALYTIC_IDS):
        for stream_scope in registry.list_active_scopes():
            if stream_scope.game_id != game_id:
                continue
            controller = registry.controller_for_scope(stream_scope)
            if controller is None:
                continue
            ctx = controller.query_context
            if not isinstance(ctx, AnalyticQueryContext):
                continue
            if not isinstance(stream_scope.perspective, int):
                continue
            shells.extend(
                _LiveShell(
                    compute_scope=ComputeScope(
                        analytic_id=analytic_id,
                        game_id=game_id,
                        perspective=stream_scope.perspective,
                        turn=stream_scope.turn_number,
                        player_id=player.id,
                    ),
                    ctx=ctx,
                    registry=registry,
                    stream_scope=stream_scope,
                    controller=controller,
                )
                for player in iter_turn_players(controller.turn)
            )
    return shells
