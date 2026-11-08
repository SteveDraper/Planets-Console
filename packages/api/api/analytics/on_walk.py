"""On-walk mark and stamp membership for Backfill earlier turns.

An accepted on-walk prepares the player's evidence mark before the first
persist, then every scoreboard persist that belongs to that walk stamps the
generation the walk started with. A scoreboard persist that belongs to no
in-flight on-walk keeps the ordinary bump.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.eliminated_player import fleet_player_eliminated_at_turn
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.off_mode import mark_is_absent
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.dag import force_root_for_entry_step, plan_compute_dag
from api.compute.orchestrator_state import ResolvedComputeRequest
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.submission_open import SubmissionOpen
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor

_ON_WALK_ANALYTICS = frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID})
_registry_lock = threading.Lock()
_walks: dict[tuple[int, int, int, int], OnWalk] = {}


@dataclass(frozen=True)
class OnWalk:
    """One accepted on-walk for a player, keyed by the shell turn it started at."""

    generation: int
    earliest_turn: int
    open_turn: int


def reset_on_walks_for_tests() -> None:
    """Drop accepted on-walks. Tests that submit with backfill on share this process."""
    with _registry_lock:
        _walks.clear()


def accept_on_walk_root(
    request: ResolvedComputeRequest,
    *,
    compute_registry: Mapping[str, AnalyticComputeRegistration],
) -> None:
    """Prepare the mark when this submission is the root of an on-walk.

    Hops keep the open they were planned with and do not prepare again.
    A player eliminated on the shell turn is not an on-walk. An absent mark
    becomes generation 1 with ``appliesFromTurn`` at the ensure baseline
    before the plan that follows. An existing mark keeps its generation, and
    ``appliesFromTurn`` moves backward only to the earliest turn this walk
    refreshes.
    """
    if not request.submission_open.backfill_earlier_turns:
        return
    scope = request.scope
    open_turn = request.submission_open.open_turn
    if scope.analytic_id not in _ON_WALK_ANALYTICS:
        return
    if not isinstance(scope.player_id, int) or not isinstance(scope.perspective, int):
        return
    if not isinstance(scope.turn, int) or open_turn is None or scope.turn != open_turn:
        return
    bundle = request.resolved_bundle()
    if bundle is None:
        return
    ctx = bundle.query_context
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return
    shell = ctx.load_turn(open_turn)
    if shell is None or fleet_player_eliminated_at_turn(shell, scope.player_id):
        return

    baseline = accelerated_ensure_floor(shell.settings, open_turn)
    player_id = scope.player_id
    perspective = scope.perspective
    services.persistence.update_evidence_mark(
        scope.game_id,
        perspective,
        player_id,
        lambda current, floor=baseline: _establish_absent_mark(current, floor),
    )
    earliest = _earliest_planned_turn(
        ctx,
        request,
        compute_registry=compute_registry,
    )
    if earliest is None:
        return
    services.persistence.update_evidence_mark(
        scope.game_id,
        perspective,
        player_id,
        lambda current, turn=earliest: _widen_existing_mark(current, turn),
    )
    mark = services.persistence.evidence_mark(scope.game_id, perspective, player_id)
    _remember_walk(
        scope.game_id,
        perspective,
        player_id,
        open_turn=open_turn,
        generation=mark.evidence_generation,
        earliest_turn=earliest,
    )


def scoreboard_persist_belongs_to_on_walk(
    orchestrator: object,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    host_turn: int,
) -> bool:
    """Whether this scoreboard persist belongs to an in-flight on-walk.

    The producing scores node carries the walk's backfill choice and shell
    turn. Membership is that walk's refresh range. A node accepted while the
    setting was off does not belong to an on-walk.
    """
    reader = getattr(orchestrator, "submission_open_for", None)
    if reader is None:
        return False
    opened = reader(
        ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=game_id,
            perspective=perspective,
            turn=host_turn,
            player_id=player_id,
        )
    )
    if not isinstance(opened, SubmissionOpen):
        return False
    if not opened.backfill_earlier_turns or opened.open_turn is None:
        return False
    walk = _walk_for(game_id, perspective, player_id, opened.open_turn)
    if walk is None:
        return False
    return walk.earliest_turn <= host_turn <= walk.open_turn


def _establish_absent_mark(current: FleetEvidenceMark, baseline: int) -> FleetEvidenceMark:
    if not mark_is_absent(current):
        return current
    return FleetEvidenceMark(evidence_generation=1, applies_from_turn=baseline)


def _widen_existing_mark(current: FleetEvidenceMark, earliest_turn: int) -> FleetEvidenceMark:
    """Move ``appliesFromTurn`` backward to ``earliest_turn``. Never forward."""
    if mark_is_absent(current):
        return current
    applies = current.applies_from_turn
    if applies is not None and earliest_turn >= applies:
        return current
    return FleetEvidenceMark(
        evidence_generation=current.evidence_generation,
        applies_from_turn=earliest_turn,
    )


def _earliest_planned_turn(
    ctx: AnalyticQueryContext,
    request: ResolvedComputeRequest,
    *,
    compute_registry: Mapping[str, AnalyticComputeRegistration],
) -> int | None:
    """Earliest host turn the on-walk plan refreshes, or None when nothing is due."""
    planned = plan_compute_dag(
        ctx,
        request.scope.analytic_id,
        compute_scope_to_export_scope(request.scope),
        compute_registry=compute_registry,
        force_root=force_root_for_entry_step(request.step_kind),
        backfill_earlier_turns=True,
    )
    turns = [node.scope.turn for node in planned if isinstance(node.scope.turn, int)]
    if not turns:
        return None
    return min(turns)


def _remember_walk(
    game_id: int,
    perspective: int,
    player_id: int,
    *,
    open_turn: int,
    generation: int,
    earliest_turn: int,
) -> None:
    key = (game_id, perspective, player_id, open_turn)
    with _registry_lock:
        existing = _walks.get(key)
        if existing is None:
            _walks[key] = OnWalk(
                generation=generation,
                earliest_turn=earliest_turn,
                open_turn=open_turn,
            )
            return
        earliest = existing.earliest_turn
        if earliest_turn < earliest:
            earliest = earliest_turn
        _walks[key] = OnWalk(
            generation=existing.generation,
            earliest_turn=earliest,
            open_turn=open_turn,
        )


def _walk_for(
    game_id: int,
    perspective: int,
    player_id: int,
    open_turn: int,
) -> OnWalk | None:
    with _registry_lock:
        return _walks.get((game_id, perspective, player_id, open_turn))
