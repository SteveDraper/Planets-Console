"""Ensure homeworld evidence aggregates via single-step refine.

Multi-turn gap-fill is owned by export/orchestrator DAG unwind
(``ENSURE_DEPENDENCIES`` self-chain). This module advances at most one turn.
Satisfaction is the shell aggregate plus the durable fleet-age stale marker.
Ledger stamps are read only when a turn is refined.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
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
from api.analytics.homeworld_locator.fleet_age_input import read_fleet_age_input_stamp
from api.analytics.homeworld_locator.location_evidence import (
    baseline_profile_location_provenances,
    definite_candidate_planet_ids,
)
from api.analytics.homeworld_locator.types import FleetAgeStaleMarker, HomeworldEvidenceAggregate
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


def prior_evidence_turn(turn: TurnInfo, *, baseline_turn: int) -> int | None:
    """Prior aggregate turn for ``turn``, or None on the baseline floor."""
    shell = turn.settings.turn
    if shell <= baseline_turn:
        return None
    ensure_floor = accelerated_ensure_floor(turn.settings, shell)
    prior = shell - 1
    if prior < ensure_floor or prior < baseline_turn:
        return baseline_turn
    return prior


def evidence_aggregate_is_current(
    aggregate: HomeworldEvidenceAggregate,
    *,
    baseline_turn: int,
    marker: FleetAgeStaleMarker | None,
) -> bool:
    """True when ``aggregate`` matches the baseline and is not fleet-age stale.

    An aggregate with no fleet-age stamp was written before stamps existed.
    A missing marker means nothing is stale. This does not read ledger files.
    """
    if aggregate.baseline_turn != baseline_turn:
        return False
    if aggregate.evidence_algorithm_version != HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
        return False
    if aggregate.fleet_age_input_stamp is None:
        return False
    if marker is not None and marker.covers(aggregate.turn):
        return False
    return True


def evidence_refined_through_shell(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    shell_turn: int,
) -> bool:
    """True when the shell aggregate is current for ``baseline_turn``.

    The durable stale marker is the fleet-age authority. This does not read
    ledger files and does not walk earlier turns. The stored aggregate stays
    in place when this returns False.
    """
    cursor = shell_turn if shell_turn > baseline_turn else baseline_turn
    aggregate = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        cursor,
    )
    if aggregate is None or aggregate.turn != cursor:
        return False
    marker = services.persistence.get_fleet_age_stale_marker(
        services.game_id,
        services.perspective,
    )
    return evidence_aggregate_is_current(
        aggregate,
        baseline_turn=baseline_turn,
        marker=marker,
    )


def _floor_prior_for_algorithm_rewrite(
    floor: HomeworldEvidenceAggregate,
    *,
    definite_planet_ids: Sequence[int],
) -> HomeworldEvidenceAggregate:
    """Clear sticky ownership and remint baseline-profile location provenances.

    OD / single-SB upserts are idempotent on re-refine; ownership intersections are
    not -- intersecting a loosened envelope into a prior narrowed set cannot restore
    wrongly excluded sectors.

    Legacy floors may lack ``baseline_profile`` rows; remint from game-global
    definites so a later weak OD mint cannot demote baseline pins at derive time.
    """
    return replace(
        floor,
        sector_owner_sets=(),
        owner_possible_sectors=(),
        location_provenances=baseline_profile_location_provenances(
            baseline_turn=floor.baseline_turn,
            definite_planet_ids=definite_planet_ids,
        ),
    )


def ensure_evidence_floor_algorithm_current(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
) -> bool:
    """Rewrite+persist the baseline floor when its algorithm version or fleet-age marker is stale.

    Sole owner of floor algorithm rewrites (export DAG skips ensuring turn 1 as
    a refine node; new floors accumulate ownership inside baseline write).
    Clears sticky ownership before re-accumulate, then stamps the current
    version and the on-disk fleet-age input. A current floor does not read
    ledger files. A marker that covers the baseline turn reads that turn's
    stamps once. Returns True when a rewrite was persisted.
    Does not delete later-turn aggregates.
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

    marker = services.persistence.get_fleet_age_stale_marker(
        services.game_id,
        services.perspective,
    )
    if evidence_aggregate_is_current(floor, baseline_turn=baseline_turn, marker=marker):
        return False

    turn = services.load_turn(baseline_turn)
    if turn is None:
        raise ValidationError(
            f"homeworld baseline turn {baseline_turn} is not stored; "
            "required to rewrite stale evidenceAlgorithmVersion or fleet-age input stamp"
        )
    # Re-read immediately before the stamp read so generation covers those files.
    observed = services.persistence.get_fleet_age_stale_marker(
        services.game_id,
        services.perspective,
    )
    stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn,
    )

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}
    computed = refine_homeworld_evidence_aggregate(
        _floor_prior_for_algorithm_rewrite(
            floor,
            definite_planet_ids=definite_candidate_planet_ids(state.candidates),
        ),
        turn=turn,
        candidates=state.candidates,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
        load_turn=services.load_turn,
        fleet_age_input_stamp=stamp,
    )
    services.persistence.put_evidence_aggregate(
        services.game_id,
        services.perspective,
        computed.aggregate,
    )
    services.persistence.advance_fleet_age_stale_marker(
        services.game_id,
        services.perspective,
        refined_turn=baseline_turn,
        observed=observed,
    )
    return True


@dataclass(frozen=True)
class EvidenceRefineStepResult:
    """Outcome of ``compute_homeworld_evidence_refine_step``."""

    aggregate: HomeworldEvidenceAggregate
    """True when refine work ran (report should be recorded after optional persist)."""
    computed: bool
    compute: EvidenceRefineComputeResult | None = None
    observed_fleet_age_stale: FleetAgeStaleMarker | None = None
    """Marker read before this step's ledger stamp read. None when not computed."""
    load_game_state_ms: float = 0.0
    load_prior_ms: float = 0.0
    step_elapsed_ms: float = 0.0


def compute_homeworld_evidence_refine_step(
    services: HomeworldLocatorComputeServices,
    *,
    turn: TurnInfo,
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
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
    return compute_homeworld_evidence_refine_step_detailed(
        services,
        turn=turn,
        fleet_persistence=fleet_persistence,
    ).aggregate


def compute_homeworld_evidence_refine_step_detailed(
    services: HomeworldLocatorComputeServices,
    *,
    turn: TurnInfo,
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
) -> EvidenceRefineStepResult:
    """Like :func:`compute_homeworld_evidence_refine_step`` with timing payload.

    Floor algorithm bumps are owned exclusively by
    :func:`ensure_evidence_floor_algorithm_current` -- callers must run that first
    when the floor may be stale. A stale floor here fails closed.
    """
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
        if floor.evidence_algorithm_version != HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
            raise ValidationError(
                f"homeworld floor evidence aggregate has stale "
                f"evidenceAlgorithmVersion {floor.evidence_algorithm_version}; "
                f"expected {HOMEWORLD_EVIDENCE_ALGORITHM_VERSION} "
                "(call ensure_evidence_floor_algorithm_current first)"
            )
        floor_marker = services.persistence.get_fleet_age_stale_marker(
            services.game_id,
            services.perspective,
        )
        if evidence_aggregate_is_current(
            floor,
            baseline_turn=baseline_turn,
            marker=floor_marker,
        ):
            return EvidenceRefineStepResult(
                aggregate=floor,
                computed=False,
                step_elapsed_ms=(time.perf_counter() - step_t0) * 1000.0,
            )
        raise ValidationError(
            "homeworld floor evidence aggregate fleet-age input is stale "
            "(call ensure_evidence_floor_algorithm_current first)"
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
    observed = services.persistence.get_fleet_age_stale_marker(
        services.game_id,
        services.perspective,
    )
    if not evidence_aggregate_is_current(prior, baseline_turn=baseline_turn, marker=observed):
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} is not fleet-age current; "
            "refine that turn before this one"
        )
    stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn,
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
        fleet_age_input_stamp=stamp,
    )
    return EvidenceRefineStepResult(
        aggregate=computed.aggregate,
        computed=True,
        compute=computed,
        observed_fleet_age_stale=observed,
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
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
) -> HomeworldEvidenceAggregate:
    """Ensure evidence at the shell turn via a single refine step, then persist.

    Prior-turn gap-fill must already have run via ``ENSURE_DEPENDENCIES`` unwind.
    ``game_state_baseline_turn`` must match the durable game-global baseline.
    When this turn is refined, ship ages are read from each roster player's
    on-disk ledger, including an approximate or generation-behind file. A
    missing file contributes no ages. A satisfied turn does not read ledgers.
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
        fleet_persistence=fleet_persistence,
    )

    step = compute_homeworld_evidence_refine_step_detailed(
        services,
        turn=shell_turn,
        fleet_persistence=fleet_persistence,
    )
    persist_ms = 0.0
    if step.computed:
        persist_t0 = time.perf_counter()
        services.persistence.put_evidence_aggregate(
            services.game_id,
            services.perspective,
            step.aggregate,
        )
        services.persistence.advance_fleet_age_stale_marker(
            services.game_id,
            services.perspective,
            refined_turn=step.aggregate.turn,
            observed=step.observed_fleet_age_stale,
        )
        persist_ms = (time.perf_counter() - persist_t0) * 1000.0
    record_evidence_refine_step_report(services, turn=shell_turn, step=step, persist_ms=persist_ms)
    return step.aggregate
