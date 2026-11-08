"""On-walk mark and stamp membership for Backfill earlier turns.

An accepted on-walk sets an absent evidence mark to generation 1 at the
ensure baseline before the plan, so ensure-final is classified against that
mark. The registered plan then widens ``appliesFromTurn`` backward only.
An empty plan rolls that establish back. Every scoreboard persist that
belongs to the walk stamps the generation the walk started with. A scoreboard
persist that belongs to no in-flight on-walk keeps the ordinary bump.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.eliminated_player import fleet_player_eliminated_at_turn
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.off_mode import mark_is_absent
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator_state import ResolvedComputeRequest
from api.compute.scope import ComputeScope
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


def prepare_absent_on_walk_mark(
    request: ResolvedComputeRequest,
) -> FleetEvidenceMark | None:
    """Set an absent on-walk mark to generation 1 at the ensure baseline.

    Call this before ``plan_compute_dag`` and outside the orchestrator lock,
    and only when this submission will register a fresh on-walk root. The plan
    then classifies ensure-final against that mark, so a generation-0 ledger
    is behind the mark and stays on the walk.

    Returns the mark this call wrote by changing an absent mark into generation
    1 at the baseline. None means this call did not write. A mark that was
    already present, including one that is already generation 1 at the
    baseline, is left unchanged and is not a rollback token. A player
    eliminated on the shell turn is not an on-walk.
    """
    located = _on_walk_shell(request)
    if located is None:
        return None
    services, baseline = located
    scope = request.scope
    established = FleetEvidenceMark(evidence_generation=1, applies_from_turn=baseline)
    wrote_absent_mark = False

    def establish(current: FleetEvidenceMark, floor: int = baseline) -> FleetEvidenceMark:
        nonlocal wrote_absent_mark
        updated = _establish_absent_mark(current, floor)
        wrote_absent_mark = mark_is_absent(current) and updated == established
        return updated

    stored = services.persistence.update_evidence_mark(
        scope.game_id,
        scope.perspective,
        scope.player_id,
        establish,
    )
    if not wrote_absent_mark:
        return None
    return stored


def remember_on_walk_from_plan(
    request: ResolvedComputeRequest,
    *,
    earliest_turn: int,
) -> None:
    """Widen the mark from the registered plan and remember that walk.

    Does not establish an absent mark. ``appliesFromTurn`` moves backward only
    to ``earliest_turn``. The caller runs this after the plan, outside the
    orchestrator lock, and before the first persist.
    """
    located = _on_walk_shell(request)
    if located is None:
        return
    services, _baseline = located
    scope = request.scope
    open_turn = request.submission_open.open_turn
    if open_turn is None:
        return
    services.persistence.update_evidence_mark(
        scope.game_id,
        scope.perspective,
        scope.player_id,
        lambda current, turn=earliest_turn: _widen_existing_mark(current, turn),
    )
    mark = services.persistence.evidence_mark(scope.game_id, scope.perspective, scope.player_id)
    if mark_is_absent(mark):
        return
    _remember_walk(
        scope.game_id,
        scope.perspective,
        scope.player_id,
        open_turn=open_turn,
        generation=mark.evidence_generation,
        earliest_turn=earliest_turn,
    )


def rollback_absent_on_walk_mark(
    request: ResolvedComputeRequest,
    established: FleetEvidenceMark,
) -> None:
    """Drop the absent-mark establish when that mark is still the one we wrote.

    An empty plan, or a submission that joined instead of planning, calls this.
    A mark another writer has already changed is left alone.
    """
    located = _on_walk_shell(request)
    if located is None:
        return
    services, _baseline = located
    scope = request.scope
    services.persistence.update_evidence_mark(
        scope.game_id,
        scope.perspective,
        scope.player_id,
        lambda current, written=established: FleetEvidenceMark() if current == written else current,
    )


def _on_walk_shell(
    request: ResolvedComputeRequest,
) -> tuple[FleetComputeServices, int] | None:
    """Fleet services and ensure baseline for an on-walk shell, or None."""
    if not request.submission_open.backfill_earlier_turns:
        return None
    scope = request.scope
    open_turn = request.submission_open.open_turn
    if scope.analytic_id not in _ON_WALK_ANALYTICS:
        return None
    if not isinstance(scope.player_id, int) or not isinstance(scope.perspective, int):
        return None
    if not isinstance(scope.turn, int) or open_turn is None or scope.turn != open_turn:
        return None
    bundle = request.resolved_bundle()
    if bundle is None:
        return None
    ctx = bundle.query_context
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return None
    shell = ctx.load_turn(open_turn)
    if shell is None or fleet_player_eliminated_at_turn(shell, scope.player_id):
        return None
    return services, accelerated_ensure_floor(shell.settings, open_turn)


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
