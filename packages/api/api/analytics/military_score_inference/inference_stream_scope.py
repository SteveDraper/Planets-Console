"""Scope key for a batch of scoreboard inference streams on one turn snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )


@dataclass(frozen=True, order=True)
class InferenceStreamScope:
    game_id: int
    perspective: int
    turn_number: int

    @classmethod
    def try_from_root(cls, scope: ComputeScope) -> InferenceStreamScope | None:
        """Stream scope of a per-player root scope, or ``None`` for a wider one.

        Reads game, perspective and turn. The rule for which scopes qualify is
        :meth:`InferenceRowScope.try_from_root`.
        """
        row_scope = InferenceRowScope.try_from_root(scope)
        return None if row_scope is None else row_scope.stream_scope

    @classmethod
    def from_root(cls, scope: ComputeScope) -> InferenceStreamScope:
        """Stream scope of a per-player root scope; raises ``ValueError`` for a wider one."""
        return InferenceRowScope.from_root(scope).stream_scope

    @classmethod
    def from_session(cls, session: InferenceRowStreamSession) -> InferenceStreamScope:
        """Stream scope the session's row belongs to."""
        return cls(
            game_id=session.game_id,
            perspective=session.perspective,
            turn_number=session.turn_number,
        )

    def root_scope(self, player_id: int) -> ComputeScope:
        """Scores root scope of one player's row on this stream scope; inverse of ``from_root``."""
        return ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=self.game_id,
            perspective=self.perspective,
            turn=self.turn_number,
            player_id=player_id,
        )


@dataclass(frozen=True, slots=True)
class InferenceRowScope:
    """One player's scoreboard row on one stream scope: the identity of its scores node."""

    stream_scope: InferenceStreamScope
    player_id: int

    @classmethod
    def try_from_root(cls, scope: ComputeScope) -> InferenceRowScope | None:
        """Row scope of a per-player root scope, or ``None`` for a wider one.

        A scope names one row only when its player, turn and perspective are
        all ints (none is a wildcard).
        """
        player_id, turn, perspective = scope.player_id, scope.turn, scope.perspective
        if not (
            isinstance(player_id, int) and isinstance(turn, int) and isinstance(perspective, int)
        ):
            return None
        return cls(
            stream_scope=InferenceStreamScope(
                game_id=scope.game_id,
                perspective=perspective,
                turn_number=turn,
            ),
            player_id=player_id,
        )

    @classmethod
    def from_root(cls, scope: ComputeScope) -> InferenceRowScope:
        """Row scope of a per-player root scope; raises ``ValueError`` for a wider one."""
        row_scope = cls.try_from_root(scope)
        if row_scope is None:
            raise ValueError(
                "inference stream scope requires a concrete player_id, turn and perspective"
            )
        return row_scope

    @classmethod
    def from_session(cls, session: InferenceRowStreamSession) -> InferenceRowScope:
        """Row scope a row session belongs to."""
        return cls(
            stream_scope=InferenceStreamScope.from_session(session),
            player_id=session.player_id,
        )

    def root_scope(self) -> ComputeScope:
        """The scores node this row's tier ladder serves; inverse of ``from_root``."""
        return self.stream_scope.root_scope(self.player_id)


def scores_root_scope_for_session(session: InferenceRowStreamSession) -> ComputeScope:
    """The scores node a row session's tier ladder serves."""
    return InferenceRowScope.from_session(session).root_scope()
