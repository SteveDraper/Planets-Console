"""Ensure homeworld evidence aggregates are refined through the shell turn."""

from __future__ import annotations

from api.analytics.homeworld_locator.compute_services import HomeworldLocatorComputeServices
from api.analytics.homeworld_locator.evidence_refine import (
    candidate_planet_ids_from_records,
    refine_homeworld_evidence_aggregate,
)
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
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


def ensure_homeworld_evidence_refined(
    services: HomeworldLocatorComputeServices,
    *,
    shell_turn: TurnInfo,
    game_state_baseline_turn: int,
) -> HomeworldEvidenceAggregate:
    """Refine and persist missing evidence aggregates through the shell turn."""
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

    if shell <= game_state_baseline_turn:
        floor = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            game_state_baseline_turn,
        )
        if floor is None:
            raise ValidationError("homeworld floor evidence aggregate missing before refine")
        return floor

    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld game-global state missing before evidence refine")

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    stored_refine_turns = [
        turn_number
        for turn_number in sorted(services.list_stored_turns())
        if game_state_baseline_turn < turn_number <= shell
    ]
    if shell not in stored_refine_turns:
        stored_refine_turns.append(shell)
        stored_refine_turns.sort()

    floor = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        game_state_baseline_turn,
    )
    last_aggregate: HomeworldEvidenceAggregate | None = (
        floor if floor is not None and floor.baseline_turn == game_state_baseline_turn else None
    )

    for turn_number in stored_refine_turns:
        existing = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            turn_number,
        )
        if (
            existing is not None
            and existing.baseline_turn == game_state_baseline_turn
            and existing.turn == turn_number
        ):
            last_aggregate = existing
            continue

        prior = last_aggregate
        if prior is None or prior.baseline_turn != game_state_baseline_turn:
            raise ValidationError(
                f"homeworld evidence aggregate before turn {turn_number} is required before refine"
            )

        turn_info = services.load_turn(turn_number)
        if turn_info is None:
            raise ValidationError(
                f"stored turn {turn_number} is required for homeworld evidence refine"
            )
        planets_by_id = {planet.id: planet for planet in turn_info.planets}

        refined = refine_homeworld_evidence_aggregate(
            prior,
            turn=turn_info,
            candidate_planet_ids_set=candidate_ids,
            planets_by_id=planets_by_id,
        )
        services.persistence.put_evidence_aggregate(
            services.game_id,
            services.perspective,
            refined,
        )
        last_aggregate = refined

    if last_aggregate is None:
        raise ValidationError("homeworld evidence refine produced no aggregate")
    return last_aggregate


def promotion_threshold() -> int:
    return get_config().homeworld_locator.evidence_promotion_threshold
