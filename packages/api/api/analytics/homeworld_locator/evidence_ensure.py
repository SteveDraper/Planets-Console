"""Ensure homeworld evidence aggregates via single-step refine.

Multi-turn gap-fill is owned by export/orchestrator DAG unwind
(``ENSURE_DEPENDENCIES`` self-chain). This module advances at most one turn.
Each turn reads on-disk fleet ledgers for ship ages. A stamp mismatch leaves
the stored aggregate in place until that turn is refined again.
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


def _fleet_age_inputs_match(
    aggregate: HomeworldEvidenceAggregate,
    *,
    baseline_turn: int,
    services: HomeworldLocatorComputeServices,
    fleet_persistence: FleetSnapshotPersistenceService | None,
    turn: TurnInfo,
) -> bool:
    if aggregate.turn != turn.settings.turn:
        return False
    if aggregate.baseline_turn != baseline_turn:
        return False
    if aggregate.evidence_algorithm_version != HOMEWORLD_EVIDENCE_ALGORITHM_VERSION:
        return False
    stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn,
    )
    return aggregate.fleet_age_input_stamp == stamp


def evidence_refined_through_shell(
    services: HomeworldLocatorComputeServices,
    *,
    baseline_turn: int,
    shell_turn: int,
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
) -> bool:
    """True when ``shell_turn`` and every prior refine turn still match their files.

    A turn matches when its baseline, evidence algorithm version, and fleet-age
    input stamp match, and it was refined from the prior aggregate's current
    stamp. The stored aggregate is left in place when this returns False.
    """
    cursor = shell_turn if shell_turn > baseline_turn else baseline_turn
    while True:
        turn = services.load_turn(cursor)
        if turn is None:
            return False
        aggregate = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            cursor,
        )
        if aggregate is None or not _fleet_age_inputs_match(
            aggregate,
            baseline_turn=baseline_turn,
            services=services,
            fleet_persistence=fleet_persistence,
            turn=turn,
        ):
            return False
        prior_turn = prior_evidence_turn(turn, baseline_turn=baseline_turn)
        if prior_turn is None:
            return True
        prior = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            prior_turn,
        )
        # A game turn that was never stored is not a fleet-age re-read. The chain
        # continues at the baseline floor when that floor is the stored prior.
        if prior is None and prior_turn != baseline_turn and services.load_turn(prior_turn) is None:
            prior = services.persistence.get_evidence_aggregate(
                services.game_id,
                services.perspective,
                baseline_turn,
            )
            prior_turn = baseline_turn
        if prior is None or aggregate.prior_fleet_age_input_stamp != prior.fleet_age_input_stamp:
            return False
        if aggregate.prior_evidence_revision != prior.evidence_revision:
            return False
        cursor = prior_turn


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
    """Rewrite+persist the baseline floor when its algorithm version or fleet-age stamp is stale.

    Sole owner of floor algorithm rewrites (export DAG skips ensuring turn 1 as
    a refine node; new floors accumulate ownership inside baseline write).
    Clears sticky ownership before re-accumulate, then stamps the current
    version and the on-disk fleet-age input. Returns True when a rewrite was persisted.
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

    turn = services.load_turn(baseline_turn)
    if turn is None:
        raise ValidationError(
            f"homeworld baseline turn {baseline_turn} is not stored; "
            "required to rewrite stale evidenceAlgorithmVersion or fleet-age input stamp"
        )
    stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn,
    )
    if (
        floor.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
        and floor.fleet_age_input_stamp == stamp
    ):
        return False

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
        existing_evidence_revision=floor.evidence_revision,
    )
    # The floor has no prior refine turn. Drop the link refine copied off the
    # cleared floor so a later turn records this floor's own stamp.
    floor_aggregate = replace(
        computed.aggregate,
        prior_fleet_age_input_stamp=None,
        prior_evidence_revision=None,
    )
    services.persistence.put_evidence_aggregate(
        services.game_id,
        services.perspective,
        floor_aggregate,
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
        fleet_persistence=fleet_persistence,
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
        floor_turn = turn if shell == baseline_turn else services.load_turn(baseline_turn)
        if floor_turn is None:
            raise ValidationError(
                f"homeworld baseline turn {baseline_turn} is not stored; "
                "required to check the fleet-age input stamp"
            )
        floor_stamp = read_fleet_age_input_stamp(
            fleet_persistence,
            game_id=services.game_id,
            perspective=services.perspective,
            turn=floor_turn,
        )
        if floor.fleet_age_input_stamp != floor_stamp:
            raise ValidationError(
                "homeworld floor evidence aggregate fleet-age input stamp does not match "
                "the ledger files (call ensure_evidence_floor_algorithm_current first)"
            )
        return EvidenceRefineStepResult(
            aggregate=floor,
            computed=False,
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
    prior_turn_info = services.load_turn(prior_turn)
    if prior_turn_info is None:
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} requires stored turn {prior_turn}"
        )
    prior_stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=prior_turn_info,
    )
    if prior.fleet_age_input_stamp != prior_stamp:
        raise ValidationError(
            f"homeworld evidence aggregate before turn {shell} has a fleet-age input "
            "stamp that does not match the ledger files"
        )

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}
    stamp = read_fleet_age_input_stamp(
        fleet_persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn=turn,
    )

    existing = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        shell,
    )
    computed = refine_homeworld_evidence_aggregate(
        prior,
        turn=turn,
        candidates=state.candidates,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
        load_turn=services.load_turn,
        fleet_age_input_stamp=stamp,
        existing_evidence_revision=0 if existing is None else existing.evidence_revision,
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
    fleet_persistence: FleetSnapshotPersistenceService | None = None,
) -> HomeworldEvidenceAggregate:
    """Ensure evidence at the shell turn via a single refine step, then persist.

    Prior-turn gap-fill must already have run via ``ENSURE_DEPENDENCIES`` unwind.
    ``game_state_baseline_turn`` must match the durable game-global baseline.
    Ship ages are read from each roster player's on-disk ledger at this turn,
    including an approximate or generation-behind file. A missing file contributes
    no ages.
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
        fleet_persistence=fleet_persistence,
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
        persist_ms = (time.perf_counter() - persist_t0) * 1000.0
    record_evidence_refine_step_report(services, turn=shell_turn, step=step, persist_ms=persist_ms)
    return step.aggregate
