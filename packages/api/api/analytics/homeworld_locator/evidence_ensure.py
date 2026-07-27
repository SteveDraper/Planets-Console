"""Ensure homeworld evidence aggregates via single-step refine.

Multi-turn gap-fill is owned by export/orchestrator DAG unwind
(``ENSURE_DEPENDENCIES`` self-chain). This module advances at most one turn.
"""

from __future__ import annotations

from api.analytics.homeworld_locator.compute_services import HomeworldLocatorComputeServices
from api.analytics.homeworld_locator.evidence_refine import (
    candidate_planet_ids_from_records,
    refine_homeworld_evidence_aggregate,
)
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.config import get_config
from api.errors import ValidationError
from api.models.game import TurnInfo


def shell_turn_number(shell_turn: TurnInfo) -> int:
    return shell_turn.settings.turn


def evidence_aggregate_at_shell_turn(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    shell_turn: int,
) -> HomeworldEvidenceAggregate | None:
    target_turn = shell_turn if shell_turn > baseline_turn else baseline_turn
    return services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        target_turn,
    )


def evidence_refined_through_shell(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    shell_turn: int,
) -> bool:
    aggregate = evidence_aggregate_at_shell_turn(
        services,
        baseline_turn=baseline_turn,
        shell_turn=shell_turn,
    )
    if aggregate is None:
        return False
    if aggregate.baseline_turn != baseline_turn:
        return False
    target_turn = shell_turn if shell_turn > baseline_turn else baseline_turn
    return aggregate.turn == target_turn


def compute_homeworld_evidence_refine_step(
    services: HomeworldLocatorComputeServices,
    *,
    turn: TurnInfo,
) -> HomeworldEvidenceAggregate:
    """Compute one refine step for ``turn`` without persisting.

    Assumes game-global state exists and the prior aggregate is already durable
    via DAG unwind / ``ENSURE_DEPENDENCIES``. When the ensure floor skips
    intermediate turns (accelerated start), the prior is the baseline floor.
    Returns the floor or an already-refined shell aggregate when no advance is
    needed.
    """
    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld game-global state missing before evidence refine")

    shell = turn.settings.turn
    baseline_turn = state.baseline_turn

    if evidence_refined_through_shell(
        services,
        baseline_turn=baseline_turn,
        shell_turn=shell,
    ):
        aggregate = evidence_aggregate_at_shell_turn(
            services,
            baseline_turn=baseline_turn,
            shell_turn=shell,
        )
        if aggregate is None:
            raise ValidationError("homeworld evidence aggregate missing after satisfaction probe")
        return aggregate

    if shell <= baseline_turn:
        floor = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            baseline_turn,
        )
        if floor is None:
            raise ValidationError("homeworld floor evidence aggregate missing before refine")
        return floor

    ensure_floor = accelerated_ensure_floor(turn.settings, shell)
    prior_turn = shell - 1
    if prior_turn < ensure_floor or prior_turn < baseline_turn:
        prior_turn = baseline_turn

    prior = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        prior_turn,
    )
    if prior is None or prior.baseline_turn != baseline_turn:
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} is required before refine"
        )

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}
    return refine_homeworld_evidence_aggregate(
        prior,
        turn=turn,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
    )


def ensure_homeworld_evidence_refined(
    services: HomeworldLocatorComputeServices,
    *,
    shell_turn: TurnInfo,
    game_state_baseline_turn: int,
) -> HomeworldEvidenceAggregate:
    """Ensure evidence at the shell turn via a single refine step, then persist.

    Prior-turn gap-fill must already have run via ``ENSURE_DEPENDENCIES`` unwind.
    ``game_state_baseline_turn`` must match the durable game-global baseline.
    """
    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld game-global state missing before evidence refine")
    if state.baseline_turn != game_state_baseline_turn:
        raise ValidationError(
            "homeworld evidence refine baseline_turn does not match game-global state"
        )

    shell = shell_turn_number(shell_turn)
    if evidence_refined_through_shell(
        services,
        baseline_turn=game_state_baseline_turn,
        shell_turn=shell,
    ):
        aggregate = evidence_aggregate_at_shell_turn(
            services,
            baseline_turn=game_state_baseline_turn,
            shell_turn=shell,
        )
        if aggregate is None:
            raise ValidationError("homeworld evidence aggregate missing after satisfaction probe")
        return aggregate

    refined = compute_homeworld_evidence_refine_step(services, turn=shell_turn)
    if shell > game_state_baseline_turn:
        services.persistence.put_evidence_aggregate(
            services.game_id,
            services.perspective,
            refined,
        )
    return refined


def promotion_threshold() -> int:
    return get_config().homeworld_locator.evidence_promotion_threshold
