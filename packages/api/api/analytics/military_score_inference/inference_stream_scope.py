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

        Reads game, perspective and turn only. A scope that does not name one
        player on one turn from one perspective (any of the three is a wildcard
        or not an int) has no stream scope.
        """
        if not all(
            isinstance(axis, int) for axis in (scope.player_id, scope.turn, scope.perspective)
        ):
            return None
        return cls(
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn_number=scope.turn,
        )

    @classmethod
    def from_root(cls, scope: ComputeScope) -> InferenceStreamScope:
        """Stream scope of a per-player root scope; raises ``ValueError`` for a wider one."""
        stream_scope = cls.try_from_root(scope)
        if stream_scope is None:
            raise ValueError(
                "inference stream scope requires a concrete player_id, turn and perspective"
            )
        return stream_scope

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


def scores_root_scope_for_session(session: InferenceRowStreamSession) -> ComputeScope:
    """The scores node a row session's tier ladder serves."""
    return InferenceStreamScope.from_session(session).root_scope(session.player_id)
