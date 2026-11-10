"""Live walk shells: which players' turns an open fleet or scoreboard stream shows.

``live_walk_shells`` is the one projection of the live fleet and scoreboard
streams to shells, one per player a stream was opened for. The walk watch
reports their keys. On-walk submission builds on the same shells and applies
its own submit filters (query context, elimination); the watch applies none,
so a player eliminated on the shell turn is still watched.

A scan reads published registry snapshots only and takes no lock, so the
watch is safe to read under the orchestrator lock.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
from api.compute.priority_band import ShellStreamWatch, WatchedShellKey
from api.streaming.table_stream.registry_catalog import LiveTableStream, live_table_streams


@dataclass(frozen=True)
class LiveWalkShell:
    """One player's shell on one live fleet or scoreboard stream."""

    key: WatchedShellKey
    stream: LiveTableStream


def live_walk_shells() -> tuple[LiveWalkShell, ...]:
    """Every player on every live fleet or scoreboard stream, from one registry scan.

    A stream whose perspective is not an int has no shell.
    """
    return tuple(
        LiveWalkShell(
            key=WatchedShellKey(
                game_id=stream.scope.game_id,
                perspective=stream.scope.perspective,
                turn=stream.scope.turn_number,
                player_id=player_id,
            ),
            stream=stream,
        )
        for stream in live_table_streams(FLEET_WALK_ANALYTIC_IDS)
        if isinstance(stream.scope.perspective, int)
        for player_id in stream.controller.player_ids
    )


def live_walk_shell_keys() -> frozenset[WatchedShellKey]:
    """The keys of every live walk shell."""
    return frozenset(shell.key for shell in live_walk_shells())


class _WalkShellStreamWatch(ShellStreamWatch):
    def watched_keys(self) -> frozenset[WatchedShellKey]:
        return live_walk_shell_keys()


WALK_SHELL_STREAM_WATCH: ShellStreamWatch = _WalkShellStreamWatch()
"""The fleet and scoreboard watch: a node is watched while a live walk shell shows it."""
