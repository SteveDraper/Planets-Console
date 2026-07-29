"""Baseline-only ensure: resolve baseline turn, infer, persist floor aggregate."""

from __future__ import annotations

import time
from dataclasses import replace

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.homeworld_locator.baseline import infer_homeworld_baseline_candidates
from api.analytics.homeworld_locator.compute_services import (
    HomeworldLocatorComputeServices,
    resolve_homeworld_services,
)
from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION
from api.analytics.homeworld_locator.evidence_ensure import evidence_aggregate_at_shell_turn
from api.analytics.homeworld_locator.evidence_refine import materialize_evidence_adjusted_candidates
from api.analytics.homeworld_locator.layout_prior import (
    apply_layout_prior_most_probable,
    layout_prior_input_fingerprint,
)
from api.analytics.homeworld_locator.origin_distance_evidence_policy import (
    effective_origin_distance_observations,
)
from api.analytics.homeworld_locator.types import (
    HomeworldBaselineEnsureResult,
    HomeworldCandidateRecord,
    HomeworldCandidateView,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
    candidate_records_from_inferred,
    empty_candidate_view,
    merge_candidates_preserving_user_asserted,
)
from api.analytics.turn_roster import players_by_id
from api.concepts.homeworld_layout import (
    homeworld_locator_inactive_reason,
    homeworld_settings_fingerprint,
    is_homeworld_locator_available,
)
from api.config import get_config
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.services.game_service import GameService


def _starbase_planet_ids(turn: TurnInfo) -> set[int]:
    return {starbase.planetid for starbase in turn.starbases}


def _player_count(turn: TurnInfo) -> int:
    return len(players_by_id(turn))


def _durable_viewpoint_perspective(
    services: HomeworldLocatorComputeServices,
    *,
    viewpoint_player_id: int,
) -> int:
    """Resolve the shell storage slot for the viewpoint player.

    Prefer ``GameService.perspective_for_player_id`` when a ``GameInfo`` roster is
    available; it must agree with the compute-scope ``services.perspective`` used
    for persistence paths. Otherwise the turn was loaded for that shell slot, so
    ``services.perspective`` is authoritative.
    """
    if services.game_info is not None:
        mapped = GameService.perspective_for_player_id(
            services.game_info, viewpoint_player_id, services.game_id
        )
        if mapped != services.perspective:
            raise ValidationError(
                f"viewpoint player id {viewpoint_player_id} maps to perspective "
                f"{mapped} for game {services.game_id}, but compute scope is "
                f"perspective {services.perspective}"
            )
        return mapped
    return services.perspective


def resolve_baseline_turn(
    services: HomeworldLocatorComputeServices,
) -> tuple[TurnInfo, int, bool]:
    """Prefer turn 1 (auto-ensure when possible); else earliest stored (degraded).

    Returns ``(turn, baseline_turn_number, baseline_degraded)``.
    """
    turn_one = services.load_turn(1)
    if turn_one is not None:
        return turn_one, 1, False

    if services.ensure_turn is not None:
        ensured = services.ensure_turn(1)
        if ensured is not None:
            return ensured, 1, False

    stored = services.list_stored_turns()
    if not stored:
        raise ValidationError(
            "homeworld locator baseline requires at least one stored turn for the perspective"
        )
    earliest = min(stored)
    turn = services.load_turn(earliest)
    if turn is None:
        raise ValidationError(f"stored baseline turn {earliest} could not be loaded")
    return turn, earliest, earliest != 1


def needs_baseline_recompute(
    services: HomeworldLocatorComputeServices,
    *,
    settings_fingerprint: tuple[object, ...],
) -> bool:
    """True when missing floor, settings changed, or turn 1 appeared after degraded."""
    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        return True
    if not services.persistence.has_baseline_floor(services.game_id, services.perspective):
        return True
    if state.settings_fingerprint != settings_fingerprint:
        return True
    if state.baseline_degraded and services.load_turn(1) is not None:
        return True
    return False


def compute_homeworld_baseline(
    services: HomeworldLocatorComputeServices,
    *,
    shell_turn: TurnInfo | None = None,
) -> HomeworldBaselineEnsureResult:
    """Compute baseline game-global + floor aggregate without a durable write.

    Orchestrator ``run_homeworld_baseline`` uses this so ``PersistencePolicy.persist``
    owns the write after epoch checks. Map/table/export call
    :func:`ensure_homeworld_baseline`, which computes then persists.
    """
    from api.analytics.homeworld_locator.evidence_refine_report import build_baseline_report
    from api.analytics.homeworld_locator.evidence_refine_timing_history import (
        record_baseline_report,
    )

    total_t0 = time.perf_counter()
    settings_source = shell_turn if shell_turn is not None else None
    if settings_source is None:
        # Fingerprint from any stored turn; prefer earliest for stability.
        stored = services.list_stored_turns()
        if not stored:
            raise ValidationError("homeworld locator ensure requires a stored turn")
        settings_source = services.load_turn(min(stored))
        if settings_source is None:
            raise ValidationError("homeworld locator ensure could not load a settings turn")

    if not is_homeworld_locator_available(settings_source.settings):
        raise ValidationError("homeworld locator is inactive for this game")

    fingerprint = homeworld_settings_fingerprint(settings_source.settings)
    if not needs_baseline_recompute(services, settings_fingerprint=fingerprint):
        state = services.persistence.get_game_state(services.game_id)
        if state is None:
            raise ValidationError(
                "homeworld locator game-global state missing after satisfaction probe"
            )
        floor = services.persistence.get_evidence_aggregate(
            services.game_id, services.perspective, state.baseline_turn
        )
        if floor is None:
            raise ValidationError(
                "homeworld locator floor aggregate missing after satisfaction probe"
            )
        record_baseline_report(
            build_baseline_report(
                game_id=services.game_id,
                perspective=services.perspective,
                baseline_turn=state.baseline_turn,
                recomputed=False,
                candidate_count=len(state.candidates),
                infer_ms=0.0,
                total_ms=(time.perf_counter() - total_t0) * 1000.0,
            )
        )
        return HomeworldBaselineEnsureResult(
            game_state=state,
            floor_aggregate=floor,
            recomputed=False,
        )

    baseline_turn_info, baseline_turn, degraded = resolve_baseline_turn(services)
    existing = services.persistence.get_game_state(services.game_id)
    min_clans = get_config().homeworld_locator.min_baseline_clans
    # Ownership matching uses Player.id; durable candidates use the shell slot.
    viewpoint_player = baseline_turn_info.player
    viewpoint_perspective = _durable_viewpoint_perspective(
        services,
        viewpoint_player_id=viewpoint_player.id,
    )
    infer_t0 = time.perf_counter()
    inferred = infer_homeworld_baseline_candidates(
        baseline_turn_info.planets,
        settings=baseline_turn_info.settings,
        viewpoint_player_id=viewpoint_player.id,
        viewpoint_perspective=viewpoint_perspective,
        viewpoint_race_id=viewpoint_player.raceid,
        player_count=_player_count(baseline_turn_info),
        starbase_planet_ids=_starbase_planet_ids(baseline_turn_info),
        min_baseline_clans=min_clans,
    )
    infer_ms = (time.perf_counter() - infer_t0) * 1000.0
    candidates = merge_candidates_preserving_user_asserted(
        inferred=candidate_records_from_inferred(inferred),
        existing=existing.candidates if existing is not None else None,
    )
    state = HomeworldLocatorGameState(
        candidates=candidates,
        baseline_turn=baseline_turn,
        baseline_degraded=degraded,
        settings_fingerprint=fingerprint,
    )
    floor = HomeworldEvidenceAggregate(
        turn=baseline_turn,
        baseline_turn=baseline_turn,
    )
    record_baseline_report(
        build_baseline_report(
            game_id=services.game_id,
            perspective=services.perspective,
            baseline_turn=baseline_turn,
            recomputed=True,
            candidate_count=len(candidates),
            infer_ms=infer_ms,
            total_ms=(time.perf_counter() - total_t0) * 1000.0,
        )
    )
    return HomeworldBaselineEnsureResult(
        game_state=state,
        floor_aggregate=floor,
        recomputed=True,
    )


def ensure_homeworld_baseline(
    services: HomeworldLocatorComputeServices,
    *,
    shell_turn: TurnInfo | None = None,
) -> HomeworldBaselineEnsureResult:
    """Run baseline-only ensure: compute then persist game-global + floor.

    Does not copy-forward empty aggregates through the shell turn (#36).
    """
    result = compute_homeworld_baseline(services, shell_turn=shell_turn)
    if not result.recomputed:
        return result
    services.persistence.invalidate_evidence_from_turn(
        services.game_id,
        services.perspective,
        result.game_state.baseline_turn,
    )
    services.persistence.put_baseline(
        services.game_id,
        services.perspective,
        result.game_state,
        result.floor_aggregate,
    )
    return result


def materialize_homeworld_candidates(
    services: HomeworldLocatorComputeServices,
    *,
    candidates: tuple[HomeworldCandidateRecord, ...],
    aggregate: HomeworldEvidenceAggregate,
    shell_turn: TurnInfo,
    baseline_turn: int,
    baseline_degraded: bool,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Ordered shell materialize: SB promote → co-sector → neighborhood → layout prior.

    Design lock: docs/design-homeworld-locator-analytic.md §4.3.1.
    """
    adjusted = materialize_evidence_adjusted_candidates(
        candidates,
        aggregate,
        planets=shell_turn.planets,
        settings_turn=shell_turn,
        player_count=_player_count(shell_turn),
    )
    input_fingerprint = layout_prior_input_fingerprint(adjusted)
    evidence_lambda = get_config().homeworld_locator.origin_distance_evidence_lambda
    if (
        aggregate.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
        and aggregate.layout_prior_input_fingerprint == input_fingerprint
        and aggregate.layout_prior_evidence_lambda == evidence_lambda
    ):
        selected = frozenset(aggregate.most_probable_planet_ids)
        return tuple(replace(row, is_most_probable=row.planet_id in selected) for row in adjusted)

    interim_view = HomeworldCandidateView(
        candidates=adjusted,
        baseline_turn=baseline_turn,
        baseline_degraded=baseline_degraded,
        available=True,
        origin_distance_observations=effective_origin_distance_observations(aggregate),
    )
    previous_most_probable = _previous_turn_most_probable_planet_ids(
        services,
        shell_turn=shell_turn,
    )
    annotated = apply_layout_prior_most_probable(
        adjusted,
        turn=shell_turn,
        view=interim_view,
        player_count=_player_count(shell_turn),
        origin_distance_observations=effective_origin_distance_observations(aggregate),
        origin_distance_evidence_lambda=evidence_lambda,
        previous_most_probable_planet_ids=previous_most_probable,
    )
    most_probable_ids = tuple(sorted(row.planet_id for row in annotated if row.is_most_probable))
    services.persistence.put_evidence_aggregate(
        services.game_id,
        services.perspective,
        replace(
            aggregate,
            layout_prior_algorithm_version=LAYOUT_PRIOR_ALGORITHM_VERSION,
            layout_prior_input_fingerprint=input_fingerprint,
            layout_prior_evidence_lambda=evidence_lambda,
            most_probable_planet_ids=most_probable_ids,
        ),
    )
    return annotated


def _previous_turn_most_probable_planet_ids(
    services: HomeworldLocatorComputeServices,
    *,
    shell_turn: TurnInfo,
) -> tuple[int, ...]:
    """Prior shell-turn selection for continuity scoring, or empty when absent."""
    turn_number = int(shell_turn.settings.turn)
    if turn_number <= 1:
        return ()
    prior = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        turn_number - 1,
    )
    if prior is None:
        return ()
    return prior.most_probable_planet_ids


def materialize_homeworld_candidate_view(
    ctx: AnalyticQueryContext,
    *,
    shell_turn: TurnInfo,
) -> HomeworldCandidateView:
    """Materialize map/table candidate view after export/DAG evidence ensure."""
    inactive = homeworld_locator_inactive_reason(shell_turn.settings)
    if inactive is not None:
        return empty_candidate_view(inactive_reason=inactive)

    services = resolve_homeworld_services(ctx)
    scope = ExportScope(
        game_id=services.game_id,
        perspective=services.perspective,
        turn=shell_turn.settings.turn,
    )
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    if not ensure_homeworld_export(ctx, scope):
        raise ValidationError(
            "homeworld locator evidence ensure did not satisfy shell scope "
            f"(game {services.game_id}, perspective {services.perspective}, "
            f"turn {scope.turn})"
        )

    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld locator game-global state missing after ensure")
    aggregate = evidence_aggregate_at_shell_turn(
        services,
        baseline_turn=state.baseline_turn,
        shell_turn=scope.turn,
    )
    if aggregate is None:
        raise ValidationError("homeworld locator shell evidence missing after ensure")

    candidates = materialize_homeworld_candidates(
        services,
        candidates=state.candidates,
        aggregate=aggregate,
        shell_turn=shell_turn,
        baseline_turn=state.baseline_turn,
        baseline_degraded=state.baseline_degraded,
    )
    return HomeworldCandidateView(
        candidates=candidates,
        baseline_turn=state.baseline_turn,
        baseline_degraded=state.baseline_degraded,
        available=True,
        inactive_reason=None,
        origin_distance_observations=effective_origin_distance_observations(aggregate),
    )
