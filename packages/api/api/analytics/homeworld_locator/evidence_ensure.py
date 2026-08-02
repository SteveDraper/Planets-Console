"""Ensure homeworld evidence aggregates via single-step refine.

Multi-turn gap-fill is owned by export/orchestrator DAG unwind
(``ENSURE_DEPENDENCIES`` self-chain). This module advances at most one turn.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass

from api.analytics.homeworld_locator.compute_services import HomeworldLocatorComputeServices
from api.analytics.homeworld_locator.constants import HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
from api.analytics.homeworld_locator.evidence_refine import (
    EvidenceRefineComputeResult,
    candidate_planet_ids_from_records,
    refine_homeworld_evidence_aggregate,
)
from api.analytics.homeworld_locator.evidence_refine_report import (
    EvidenceRefineOuterTimingMs,
    build_evidence_refine_report,
)
from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    record_evidence_refine_report,
)
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
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
    if aggregate.evidence_algorithm_version != HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
        return False
    target_turn = shell_turn if shell_turn > baseline_turn else baseline_turn
    return aggregate.turn == target_turn


def ensure_evidence_floor_algorithm_current(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    fleet_built_turns: Mapping[int, int] | None = None,
) -> bool:
    """Rewrite+persist the baseline floor when ``evidenceAlgorithmVersion`` is stale.

    Export DAG walks treat turn 1 as ``_is_at_baseline`` and skip ensuring it, so a
    shell open at turn > 1 must upgrade the floor here before chain advance.
    Returns True when a rewrite was persisted.
    """
    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld game-global state missing before evidence floor rewrite")
    if state.baseline_turn != baseline_turn:
        raise ValidationError(
            "homeworld evidence floor rewrite baseline_turn does not match game-global state"
        )

    floor = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        baseline_turn,
    )
    if floor is None:
        raise ValidationError("homeworld floor evidence aggregate missing before algorithm rewrite")
    if floor.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
        return False

    turn = services.load_turn(baseline_turn)
    if turn is None:
        raise ValidationError(
            f"homeworld baseline turn {baseline_turn} is not stored; "
            "required to rewrite stale evidenceAlgorithmVersion"
        )

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}
    computed = refine_homeworld_evidence_aggregate(
        floor,
        turn=turn,
        candidates=state.candidates,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
        load_turn=services.load_turn,
        fleet_built_turns=fleet_built_turns,
    )
    services.persistence.put_evidence_aggregate(
        services.game_id,
        services.perspective,
        computed.aggregate,
    )
    return True


@dataclass(frozen=True)
class EvidenceRefineStepResult:
    """Outcome of ``compute_homeworld_evidence_refine_step``."""

    aggregate: HomeworldEvidenceAggregate
    """True when refine work ran (report should be recorded after optional persist)."""
    computed: bool
    compute: EvidenceRefineComputeResult | None = None
    load_game_state_ms: float = 0.0
    load_prior_ms: float = 0.0
    step_elapsed_ms: float = 0.0


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

    Prefer :func:`compute_homeworld_evidence_refine_step_detailed` when the
    caller will record timing telemetry.
    """
    return compute_homeworld_evidence_refine_step_detailed(services, turn=turn).aggregate


def compute_homeworld_evidence_refine_step_detailed(
    services: HomeworldLocatorComputeServices,
    *,
    turn: TurnInfo,
    fleet_built_turns: Mapping[int, int] | None = None,
) -> EvidenceRefineStepResult:
    """Like :func:`compute_homeworld_evidence_refine_step`` with timing payload."""
    step_t0 = time.perf_counter()
    state_t0 = time.perf_counter()
    state = services.persistence.get_game_state(services.game_id)
    load_game_state_ms = (time.perf_counter() - state_t0) * 1000.0
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
        return EvidenceRefineStepResult(
            aggregate=aggregate,
            computed=False,
            step_elapsed_ms=(time.perf_counter() - step_t0) * 1000.0,
        )

    if shell <= baseline_turn:
        floor = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            baseline_turn,
        )
        if floor is None:
            raise ValidationError("homeworld floor evidence aggregate missing before refine")
        if floor.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
            return EvidenceRefineStepResult(
                aggregate=floor,
                computed=False,
                step_elapsed_ms=(time.perf_counter() - step_t0) * 1000.0,
            )
        # Algo bump on floor-only shell: re-run refine on the baseline turn so
        # ownership (and future evidence policy) rewrites the floor aggregate.
        candidate_ids = candidate_planet_ids_from_records(state.candidates)
        planets_by_id = {planet.id: planet for planet in turn.planets}
        computed = refine_homeworld_evidence_aggregate(
            floor,
            turn=turn,
            candidates=state.candidates,
            candidate_planet_ids_set=candidate_ids,
            planets_by_id=planets_by_id,
            load_turn=services.load_turn,
            fleet_built_turns=fleet_built_turns,
        )
        return EvidenceRefineStepResult(
            aggregate=computed.aggregate,
            computed=True,
            compute=computed,
            load_game_state_ms=load_game_state_ms,
            load_prior_ms=0.0,
            step_elapsed_ms=(time.perf_counter() - step_t0) * 1000.0,
        )

    ensure_floor = accelerated_ensure_floor(turn.settings, shell)
    prior_turn = shell - 1
    if prior_turn < ensure_floor or prior_turn < baseline_turn:
        prior_turn = baseline_turn

    prior_t0 = time.perf_counter()
    prior = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        prior_turn,
    )
    load_prior_ms = (time.perf_counter() - prior_t0) * 1000.0
    if prior is None or prior.baseline_turn != baseline_turn:
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} is required before refine"
        )
    if prior.evidence_algorithm_version != HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} has stale "
            f"evidenceAlgorithmVersion {prior.evidence_algorithm_version}; "
            f"expected {HOMEWORLD_EVIDENCE_ALGORITHM_VERSION}"
        )

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}

    computed = refine_homeworld_evidence_aggregate(
        prior,
        turn=turn,
        candidates=state.candidates,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
        load_turn=services.load_turn,
        fleet_built_turns=fleet_built_turns,
    )
    return EvidenceRefineStepResult(
        aggregate=computed.aggregate,
        computed=True,
        compute=computed,
        load_game_state_ms=load_game_state_ms,
        load_prior_ms=load_prior_ms,
        step_elapsed_ms=(time.perf_counter() - step_t0) * 1000.0,
    )


def record_evidence_refine_step_report(
    services: HomeworldLocatorComputeServices,
    *,
    turn: TurnInfo,
    step: EvidenceRefineStepResult,
    persist_ms: float = 0.0,
) -> None:
    """Record timing for a computed refine step (no-op when ``step.computed`` is false)."""
    if not step.computed or step.compute is None:
        return
    record_evidence_refine_report(
        build_evidence_refine_report(
            game_id=services.game_id,
            turn=turn.settings.turn,
            perspective=services.perspective,
            baseline_turn=step.aggregate.baseline_turn,
            timing_inner=step.compute.timing,
            timing_outer=EvidenceRefineOuterTimingMs(
                load_game_state_ms=step.load_game_state_ms,
                load_prior_ms=step.load_prior_ms,
                refine_inner_ms=step.compute.timing.total_ms,
                persist_ms=persist_ms,
                total_ms=step.step_elapsed_ms + persist_ms,
            ),
            counts=step.compute.counts,
        )
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

    ensure_evidence_floor_algorithm_current(
        services,
        baseline_turn=game_state_baseline_turn,
    )

    step = compute_homeworld_evidence_refine_step_detailed(services, turn=shell_turn)
    persist_ms = 0.0
    if step.computed:
        # Includes baseline-floor algorithm bumps (shell <= baseline_turn): the
        # rewrite must land durably or later turns see a stale prior and fail.
        persist_t0 = time.perf_counter()
        services.persistence.put_evidence_aggregate(
            services.game_id,
            services.perspective,
            step.aggregate,
        )
        persist_ms = (time.perf_counter() - persist_t0) * 1000.0
    record_evidence_refine_step_report(services, turn=shell_turn, step=step, persist_ms=persist_ms)
    return step.aggregate
