"""Submit on-walks for live fleet and scoreboard streams when the setting turns on.

A turn with no live stream stays quiet. One player does not wait for another.
A player who still has a non-terminal fleet or scoreboard node from an
off-setting walk is submitted after that node completes, and only while the
setting is still on and that stream is still live. The follow-up is a
``force_fresh`` submit after the orchestrator has released its lock. A failed
off-setting node is terminal for the wait. A running off-setting scoreboard
does not absorb the on-walk by attach. Streams are not re-admitted, so stored
rows do not return to turn load.
"""

from __future__ import annotations

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
            _OffSettingWalkWaiter(orch, player, player_shells).start()
        else:
            _submit_shells(orch, player_shells)


class _OffSettingWalkWaiter:
    """Submits one player's shells once that player's off-setting nodes are terminal.

    The listener is registered before the first check, and the listener and
    that check share one ``_finish``, so a node that completes in between is
    submitted once. A parked node stays a blocker. A failed node is terminal.
    A non-terminal off-setting scoreboard is a blocker, so the on-walk is not
    attached to the node that walk opened.
    """

    def __init__(
        self,
        orchestrator: ComputeOrchestrator,
        player: _PlayerKey,
        shells: list[_LiveShell],
    ) -> None:
        self._orchestrator = orchestrator
        self._player = player
        self._shells = shells
        self._gate = threading.Lock()
        self._is_finished = False
        self._unregister: Callable[[], None] | None = None

    def start(self) -> None:
        self._unregister = self._orchestrator.observers.register_scope_outcome_listener(
            self._on_outcome
        )
        self._try_finish()

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
        with self._gate:
            if self._is_finished:
                return
            self._is_finished = True
            unregister = self._unregister
        if unregister is not None:
            unregister()
        _submit_shells(self._orchestrator, self._shells)


def _submit_shells(orchestrator: ComputeOrchestrator, shells: list[_LiveShell]) -> None:
    for shell in shells:
        if not shell.still_live():
            continue
        if not shell.ctx.backfill_earlier_turns_enabled():
            continue
        orchestrator.submit(
            ComputeRequest(
                scope=shell.compute_scope,
                priority_band="stream_attached",
                force_fresh=True,
                ctx=shell.ctx,
            )
        )
        shell.emit_accepted()


def _has_off_setting_walk(orchestrator: ComputeOrchestrator, player: _PlayerKey) -> bool:
    """Whether the player has a non-terminal fleet or scores node opened with the setting off."""
    return any(
        not view.is_terminal and not view.backfill_earlier_turns
        for view in orchestrator.node_opens_for_player(
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
