"""One scoreboard row's tier ladder, as a single value.

A ladder is the policy ladder state plus, for a row solved in accelerated
segments (split or backfill), the segment orchestration that records each
segment's solve. The two belong together: hand-over moves both to another
run, and progress in one without the other would combine segments from
different ladders. Both held parts are mutable: tier steps and fleet resolution
update the ``ladder_state`` in place, and recording a finished segment
updates the ``orchestration`` in place. ``TierLadder`` itself is frozen, so
only the pairing changes as a unit: a rebuild, a hand-over or the move to the
next accelerated segment installs a new pairing.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.hull_catalog_mask import resolve_hull_catalog_mask
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    new_ladder_state,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


@dataclass(frozen=True, slots=True)
class TierLadder:
    """A row's policy ladder state and, when it solves in segments, their orchestration.

    ``orchestration`` is None for a row that solves one segment (no accelerated
    split or backfill).
    """

    ladder_state: PolicyLadderState
    orchestration: InferenceStreamOrchestration | None = None


@dataclass(frozen=True, slots=True)
class LadderRebuild:
    """What a ladder rebuild seeds from: the player's hull mask user override.

    A claim takes it from the same mask snapshot it forms its epoch from, so the
    rebuilt ladder solves under the mask that epoch names.
    """

    user_override: frozenset[int] | None


def rebuild_tier_ladder(
    session: InferenceRowStreamSession,
    previous: TierLadder,
    rebuild: LadderRebuild,
) -> TierLadder:
    """A fresh ladder for ``session`` under ``rebuild``'s mask, with no tier or segment solved.

    Sets ``session.resolved_mask``, which the fresh ladder seeds from. Every
    other seeded input comes from the session, whose fleet fields the wire
    build has just refreshed. The counterparty fleet loader is carried over
    from ``previous``. Caller holds the run's ``tier_lock``.
    """
    session.resolved_mask = resolve_hull_catalog_mask(
        session.turn, session.player_id, user_enabled_hull_ids=rebuild.user_override
    )
    ladder_state = new_ladder_state(
        session,
        load_counterparty_fleet=previous.ladder_state.load_counterparty_fleet,
    )
    orchestration = None if previous.orchestration is None else previous.orchestration.restarted()
    return TierLadder(ladder_state, orchestration)
