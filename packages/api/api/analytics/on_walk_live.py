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
from typing import Protocol

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import get_fleet_table_stream_registry
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeOrchestrator, NodeOpenView
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.orchestrator_state import ComputeRequest
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.models.game import TurnInfo

_OFF_SETTING_BLOCKERS = frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID})


class _LiveStreamController(Protocol):
    """Fleet or inference table stream that can accept an on-walk."""

    @property
    def turn(self) -> TurnInfo: ...

    @property
    def query_context(self) -> AnalyticQueryContext | None: ...

    def emit_work_accepted(self, player_id: int) -> None: ...


@dataclass(frozen=True)
class _LiveShell:
    analytic_id: str
    game_id: int
    perspective: int
    turn: int
    player_id: int
    ctx: AnalyticQueryContext
    still_live: Callable[[], bool]
    emit_accepted: Callable[[], None]


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
    by_player: dict[tuple[int, int], list[_LiveShell]] = {}
    for shell in shells:
        by_player.setdefault((shell.perspective, shell.player_id), []).append(shell)
    for (perspective, player_id), player_shells in by_player.items():
        blockers = _off_setting_walk_blockers(
            orch,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
        )
        if not blockers:
            _submit_shells(orch, player_shells)
            continue
        _submit_after_off_setting_walk(orch, player_shells, blockers)


def _submit_after_off_setting_walk(
    orchestrator: ComputeOrchestrator,
    shells: list[_LiveShell],
    blockers: tuple[ComputeScope, ...],
) -> None:
    """Submit ``shells`` once every off-setting fleet or scoreboard blocker is terminal.

    ``blockers`` is the set observed before the listener was registered. The
    listener and the check after registration share one finish, so a node that
    completes in between is submitted once. A parked node stays a blocker.
    A failed node is terminal. A non-terminal off-setting scoreboard is a
    blocker, so the on-walk is not attached to the node that walk opened.
    """
    if not blockers:
        _submit_shells(orchestrator, shells)
        return
    gate = threading.Lock()
    finished = False
    unregister_holder: list[Callable[[], None] | None] = [None]
    player_shell = shells[0]

    def try_finish() -> None:
        nonlocal finished
        if _off_setting_walk_blockers(
            orchestrator,
            game_id=player_shell.game_id,
            perspective=player_shell.perspective,
            player_id=player_shell.player_id,
        ):
            return
        with gate:
            if finished:
                return
            finished = True
            registered = unregister_holder[0]
        if registered is not None:
            registered()
        _submit_shells(orchestrator, shells)

    def on_outcome(snapshot: ScopeLifecycleSnapshot) -> None:
        if snapshot.state == "parked":
            return
        if snapshot.state not in {"complete", "failed"}:
            return
        if snapshot.scope.analytic_id not in _OFF_SETTING_BLOCKERS:
            return
        if snapshot.scope.player_id != player_shell.player_id:
            return
        if snapshot.scope.game_id != player_shell.game_id:
            return
        if snapshot.scope.perspective != player_shell.perspective:
            return
        try_finish()

    unregister_holder[0] = orchestrator.observers.register_scope_outcome_listener(on_outcome)
    try_finish()


def _submit_shells(orchestrator: ComputeOrchestrator, shells: list[_LiveShell]) -> None:
    for shell in shells:
        if not shell.still_live():
            continue
        if not shell.ctx.backfill_earlier_turns_enabled():
            continue
        orchestrator.submit(
            ComputeRequest(
                scope=ComputeScope(
                    analytic_id=shell.analytic_id,
                    game_id=shell.game_id,
                    perspective=shell.perspective,
                    turn=shell.turn,
                    player_id=shell.player_id,
                ),
                priority_band="stream_attached",
                force_fresh=True,
                ctx=shell.ctx,
            )
        )
        shell.emit_accepted()


def _off_setting_walk_blockers(
    orchestrator: ComputeOrchestrator,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> tuple[ComputeScope, ...]:
    return tuple(
        view.scope
        for view in orchestrator.node_opens_for_player(
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            analytic_ids=_OFF_SETTING_BLOCKERS,
        )
        if _blocks_on_walk(view)
    )


def _blocks_on_walk(view: NodeOpenView) -> bool:
    return not view.is_terminal and not view.backfill_earlier_turns


def _live_shells(game_id: int) -> tuple[_LiveShell, ...]:
    shells: list[_LiveShell] = []
    shells.extend(_shells_for_registry(game_id, analytic_id=FLEET_ANALYTIC_ID))
    shells.extend(_shells_for_registry(game_id, analytic_id=SCORES_ANALYTIC_ID))
    return tuple(shells)


def _shells_for_registry(game_id: int, *, analytic_id: str) -> list[_LiveShell]:
    if analytic_id == FLEET_ANALYTIC_ID:
        registry = get_fleet_table_stream_registry()
    else:
        registry = get_inference_table_stream_registry()
    shells: list[_LiveShell] = []
    for scope in registry.list_active_scopes():
        if scope.game_id != game_id:
            continue
        controller = registry.controller_for_scope(scope)
        built = _shells_from_controller(analytic_id, scope, controller)
        shells.extend(built)
    return shells


def _shells_from_controller(
    analytic_id: str,
    scope: FleetTableStreamScope | InferenceStreamScope,
    controller: _LiveStreamController | None,
) -> list[_LiveShell]:
    if controller is None:
        return []
    ctx = controller.query_context
    if not isinstance(ctx, AnalyticQueryContext):
        return []
    if not isinstance(scope.perspective, int):
        return []

    def still_live(
        bound_scope: FleetTableStreamScope | InferenceStreamScope = scope,
        bound_analytic: str = analytic_id,
    ) -> bool:
        return _controller_is_attached(bound_analytic, bound_scope)

    shells: list[_LiveShell] = []
    for player in iter_turn_players(controller.turn):
        player_id = player.id

        def emit(
            bound_controller: _LiveStreamController = controller,
            bound_player: int = player_id,
        ) -> None:
            bound_controller.emit_work_accepted(bound_player)

        shells.append(
            _LiveShell(
                analytic_id=analytic_id,
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn=scope.turn_number,
                player_id=player_id,
                ctx=ctx,
                still_live=still_live,
                emit_accepted=emit,
            )
        )
    return shells


def _controller_is_attached(
    analytic_id: str,
    scope: FleetTableStreamScope | InferenceStreamScope,
) -> bool:
    if analytic_id == FLEET_ANALYTIC_ID and isinstance(scope, FleetTableStreamScope):
        return get_fleet_table_stream_registry().controller_for_scope(scope) is not None
    if isinstance(scope, InferenceStreamScope):
        return get_inference_table_stream_registry().controller_for_scope(scope) is not None
    return False
