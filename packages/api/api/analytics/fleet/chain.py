"""Materialize fleet turn snapshots by chaining from prior turns."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

from api.analytics.fleet.compute_plane.turn_delta import (
    advance_ledger_to_turn,
    apply_fleet_turn_delta_for_player,
)
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.materialization_provenance import resolve_fleet_materialization_provenance
from api.analytics.fleet.observation_ingest import (
    apply_id_bounds_then_observations,
    ingest_turn_ship_observations,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.analytics.turn_roster import iter_turn_players
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.errors import ConflictError, NotFoundError, ValidationError
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


FleetMaterializationProgressCallback = Callable[
    [PersistedFleetLedger, int],
    None,
]


class _FleetSnapshotInvalidated(Exception):
    """Gap-fill observed a concurrent fleet snapshot invalidation."""


_active_gap_fill_coherence = threading.local()


def active_gap_fill_coherence() -> _GapFillCoherence | None:
    return getattr(_active_gap_fill_coherence, "coherence", None)


def set_active_gap_fill_coherence(
    coherence: _GapFillCoherence | None,
    token: object | None = None,
) -> object:
    if token is not None:
        _active_gap_fill_coherence.coherence = coherence
        return token
    previous = active_gap_fill_coherence()
    _active_gap_fill_coherence.coherence = coherence
    return previous


@contextmanager
def gap_fill_coherence_scope(coherence: _GapFillCoherence) -> Iterator[None]:
    token = set_active_gap_fill_coherence(coherence)
    try:
        yield
    finally:
        set_active_gap_fill_coherence(None, token)


_active_gap_fill_progress = threading.local()


def active_gap_fill_progress_callback() -> FleetMaterializationProgressCallback | None:
    getter = getattr(_active_gap_fill_progress, "getter", None)
    if getter is None:
        return None
    return getter()


def _set_active_gap_fill_progress_getter(
    getter: Callable[[], FleetMaterializationProgressCallback | None] | None,
    token: object | None = None,
) -> object:
    if token is not None:
        _active_gap_fill_progress.getter = getter
        return token
    previous = getattr(_active_gap_fill_progress, "getter", None)
    _active_gap_fill_progress.getter = getter
    return previous


@contextmanager
def gap_fill_progress_scope(
    callback_getter: Callable[[], FleetMaterializationProgressCallback | None],
) -> Iterator[None]:
    token = _set_active_gap_fill_progress_getter(callback_getter)
    try:
        yield
    finally:
        _set_active_gap_fill_progress_getter(None, token)


def emit_gap_fill_leg_progress(
    persisted: PersistedFleetLedger,
    materialize_turn: int,
) -> None:
    """Notify the active inflight gap-fill callback after one materialized leg."""
    callback = active_gap_fill_progress_callback()
    if callback is not None:
        callback(persisted, materialize_turn)


@dataclass
class _GapFillCoherence:
    """Guard gap-fill puts against concurrent fleet snapshot invalidation."""

    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    player_id: int
    generation: int

    def put_ledger(
        self,
        turn_number: int,
        persisted: PersistedFleetLedger,
    ) -> None:
        self._assert_unchanged()
        # Immediate notify (N1'): orchestrator also fires per final persist after
        # complete; leaf must not batch via gap_fill_deferred_notifications.
        self.persistence.put_ledger(
            self.game_id,
            self.perspective,
            turn_number,
            self.player_id,
            persisted,
        )
        self._assert_unchanged()

    def _assert_unchanged(self) -> None:
        if (
            self.persistence.player_invalidation_generation(
                self.game_id,
                self.perspective,
                self.player_id,
            )
            != self.generation
        ):
            raise _FleetSnapshotInvalidated()


def ensure_fleet_baseline(
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    baseline_turn_number: int | None = None,
) -> FleetTurnSnapshot:
    """Return an empty per-player fleet ledger for turn 1 (fleet ensure baseline)."""
    snapshot_turn = baseline_turn_number if baseline_turn_number is not None else turn.settings.turn
    return FleetTurnSnapshot(
        analytic_id=ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=snapshot_turn,
        players=[
            FleetAcquisitionLedger(player_id=player.id, player_name=player.username)
            for player in iter_turn_players(turn)
        ],
    )


def ensure_fleet_baseline_for_player(
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    player_id: int,
) -> FleetAcquisitionLedger:
    """Return an empty fleet ledger for one player at the fleet ensure baseline."""
    for player in iter_turn_players(turn):
        if player.id == player_id:
            return FleetAcquisitionLedger(player_id=player.id, player_name=player.username)
    raise ValidationError(
        f"player_id {player_id} is not on the turn {turn.settings.turn} roster",
    )


def advance_snapshot_to_turn(
    prior: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
) -> FleetTurnSnapshot:
    """Copy turn T-1 ledger state forward to shell turn T."""
    ledgers_by_player_id = {ledger.player_id: ledger for ledger in prior.players}
    players: list[FleetAcquisitionLedger] = []
    for player in iter_turn_players(turn):
        prior_ledger = ledgers_by_player_id.get(player.id)
        if prior_ledger is None:
            players.append(FleetAcquisitionLedger(player_id=player.id, player_name=player.username))
            continue
        ledger = copy.deepcopy(prior_ledger)
        ledger.player_name = player.username
        players.append(ledger)
    return FleetTurnSnapshot(
        analytic_id=prior.analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn.settings.turn,
        players=players,
    )


def apply_fleet_turn_delta(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    inference_materialization: FleetInferenceMaterialization | None = None,
    turn_context: FleetTurnContext | None = None,
) -> FleetTurnSnapshot:
    """Apply all turn-T fleet evidence deltas for materialization."""
    resolved_context = (
        turn_context if turn_context is not None else FleetTurnContext.from_turn(turn)
    )
    snapshot = ingest_turn_inferred_acquisitions(
        snapshot,
        turn,
        inference_materialization=inference_materialization,
    )
    snapshot = ingest_turn_ship_observations(snapshot, turn, turn_context=resolved_context)
    return snapshot


def _find_chain_anchor_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn_number: int,
    *,
    min_anchor_turn: int = 1,
) -> tuple[int, PersistedFleetLedger | None]:
    for prior_turn_number in range(turn_number - 1, min_anchor_turn - 1, -1):
        prior_ledger = persistence.get_ledger(
            game_id,
            perspective,
            prior_turn_number,
            player_id,
        )
        if prior_ledger is not None:
            return prior_turn_number, prior_ledger
    return 0, None


def _first_stored_rst_turn(
    load_turn: Callable[[int], TurnInfo | None],
    turn_number: int,
    *,
    min_turn: int = 1,
) -> int | None:
    """Return the lowest stored RST turn in ``min_turn..turn_number``, if any."""
    for stored_turn_number in range(min_turn, turn_number + 1):
        if load_turn(stored_turn_number) is not None:
            return stored_turn_number
    return None


def _roster_player_ids(turn: TurnInfo) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def _chain_floor(
    load_turn: Callable[[int], TurnInfo | None],
    target_turn: int,
) -> int:
    """Lowest turn fleet gap-fill may require when targeting ``target_turn``."""
    target_info = load_turn(target_turn)
    if target_info is None:
        return 1
    return accelerated_ensure_floor(target_info.settings, target_turn)


def _find_gap_start_turn(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    target_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> int:
    """Return the first turn in ``floor..target_turn`` lacking an ensure-final snapshot."""
    chain_floor = _chain_floor(load_turn, target_turn)
    for turn_number in range(chain_floor, target_turn + 1):
        turn_info = load_turn(turn_number)
        if turn_info is None:
            continue
        snapshot = persistence.get_snapshot(game_id, perspective, turn_number)
        if not _is_fleet_snapshot_cache_hit(
            persistence,
            game_id,
            perspective,
            turn_number,
            turn_info,
            snapshot,
        ):
            return turn_number
    return target_turn + 1


def _find_gap_start_turn_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    target_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> int:
    """Return the first turn in ``floor..target_turn`` lacking ensure-final ledger for P."""
    chain_floor = _chain_floor(load_turn, target_turn)
    for turn_number in range(chain_floor, target_turn + 1):
        if load_turn(turn_number) is None:
            continue
        if not persistence.has_final_ledger(game_id, perspective, turn_number, player_id):
            return turn_number
    return target_turn + 1


def _snapshot_has_all_roster_players(snapshot: FleetTurnSnapshot, turn: TurnInfo) -> bool:
    roster_ids = set(_roster_player_ids(turn))
    present_ids = {ledger.player_id for ledger in snapshot.players}
    return roster_ids <= present_ids


def _snapshot_is_provenance_final_for_all_roster_players(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn_number: int,
    turn: TurnInfo,
) -> bool:
    """True when every roster player has an ensure-final ledger at this turn."""
    for player_id in _roster_player_ids(turn):
        if not persistence.has_final_ledger(game_id, perspective, turn_number, player_id):
            return False
    return True


def _is_fleet_ledger_cache_hit(persisted: PersistedFleetLedger) -> bool:
    """Return whether a cached per-player ledger may short-circuit gap-fill."""
    return persisted.provenance.is_final


def _is_fleet_snapshot_cache_hit(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn_number: int,
    turn: TurnInfo,
    snapshot: FleetTurnSnapshot | None,
) -> bool:
    """Return whether a cached turn snapshot may short-circuit gap-fill."""
    return (
        snapshot is not None
        and _snapshot_has_all_roster_players(snapshot, turn)
        and _snapshot_is_provenance_final_for_all_roster_players(
            persistence,
            game_id,
            perspective,
            turn_number,
            turn,
        )
    )


def _materialize_and_persist_player_turn(
    coherence: _GapFillCoherence,
    *,
    materialize_turn: int,
    player_id: int,
    prior_persisted: PersistedFleetLedger | None,
    prior_ledger: FleetAcquisitionLedger,
    turn_info: TurnInfo,
    turn_context: FleetTurnContext,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
) -> PersistedFleetLedger:
    ledger = advance_ledger_to_turn(prior_ledger, turn_info)
    ledger = apply_fleet_turn_delta_for_player(
        ledger,
        turn_context,
        game_id=game_id,
        perspective=perspective,
        inference_materialization=inference_materialization,
    )
    # Delta owns acquisitions + bounds; observations use the same bounds→observe
    # helper as orchestrator persist (re-tighten is idempotent).
    apply_id_bounds_then_observations(
        ledger,
        turn_context,
        perspective=perspective,
    )
    provenance = resolve_fleet_materialization_provenance(
        materialize_turn=materialize_turn,
        prior_persisted=prior_persisted,
        turn_context=turn_context,
        player_id=player_id,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )
    persisted = PersistedFleetLedger(ledger=ledger, provenance=provenance)
    coherence.put_ledger(materialize_turn, persisted)
    return persisted


def _materialize_fleet_ledger_chain_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
    coherence: _GapFillCoherence,
    turn_context_cache: dict[int, FleetTurnContext],
) -> PersistedFleetLedger:
    """Gap-fill one player's fleet ledger from anchor through turn T.

    Used by roster snapshot/compute multi-turn unwind and fixture seeding.
    Player-scoped leaf ``get_or_materialize_fleet_ledger_for_player`` remains
    single-turn (export materialize after ensure); orchestrator ensure is the
    durable multi-turn path for that leaf.
    """
    turn_number = turn.settings.turn

    existing = persistence.get_ledger(game_id, perspective, turn_number, player_id)
    if existing is not None and _is_fleet_ledger_cache_hit(existing):
        return existing

    loaded_turns: dict[int, TurnInfo | None] = {}

    def cached_load(stored_turn_number: int) -> TurnInfo | None:
        if stored_turn_number not in loaded_turns:
            loaded_turns[stored_turn_number] = load_turn(stored_turn_number)
        return loaded_turns[stored_turn_number]

    resolved_inference_materialization = (
        FleetInferenceMaterialization(
            inference=inference_materialization.inference,
            load_turn=cached_load,
        )
        if inference_materialization is not None
        else None
    )

    def require_turn(materialize_turn: int) -> TurnInfo:
        if materialize_turn == turn_number:
            return turn
        turn_info = cached_load(materialize_turn)
        if turn_info is None:
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {materialize_turn} "
                f"for game {game_id} perspective {perspective}"
            )
        return turn_info

    def cached_turn_context_for(materialize_turn: int, turn_info: TurnInfo) -> FleetTurnContext:
        if materialize_turn not in turn_context_cache:
            turn_context_cache[materialize_turn] = FleetTurnContext.from_turn(turn_info)
        return turn_context_cache[materialize_turn]

    chain_floor = accelerated_ensure_floor(turn.settings, turn_number)

    def require_prior_rst(materialize_turn: int, *, allow_missing_prior_rst: bool) -> None:
        if materialize_turn <= chain_floor:
            return
        prior_turn_number = materialize_turn - 1
        if allow_missing_prior_rst:
            return
        if cached_load(prior_turn_number) is None:
            raise NotFoundError(
                f"fleet snapshot chain requires stored turn {prior_turn_number} "
                f"for game {game_id} perspective {perspective}"
            )

    anchor_turn, anchor_persisted = _find_chain_anchor_for_player(
        persistence,
        game_id,
        perspective,
        player_id,
        turn_number,
        min_anchor_turn=chain_floor,
    )
    first_stored_rst = _first_stored_rst_turn(
        cached_load,
        turn_number,
        min_turn=chain_floor,
    )
    skip_missing_prefix_rst = False
    start_turn = anchor_turn + 1 if anchor_turn >= chain_floor else chain_floor
    current_ledger = anchor_persisted.ledger if anchor_persisted is not None else None
    current_persisted = anchor_persisted

    def emit_leg_progress(
        persisted_leg: PersistedFleetLedger,
        materialize_turn: int,
    ) -> None:
        nonlocal current_ledger
        emit_gap_fill_leg_progress(persisted_leg, materialize_turn)
        current_ledger = persisted_leg.ledger

    if (
        anchor_turn == 0
        and turn_number > chain_floor
        and first_stored_rst is not None
        and first_stored_rst > chain_floor
    ):
        skip_missing_prefix_rst = True
        start_turn = first_stored_rst
        first_rst_turn = require_turn(start_turn)
        current_ledger = advance_ledger_to_turn(
            ensure_fleet_baseline_for_player(
                game_id,
                perspective,
                first_rst_turn,
                player_id,
            ),
            first_rst_turn,
        )
        current_persisted = None
    elif anchor_turn == 0:
        baseline_turn = require_turn(chain_floor)
        current_persisted = _materialize_and_persist_player_turn(
            coherence,
            materialize_turn=chain_floor,
            player_id=player_id,
            prior_persisted=None,
            prior_ledger=ensure_fleet_baseline_for_player(
                game_id,
                perspective,
                baseline_turn,
                player_id,
            ),
            turn_info=baseline_turn,
            turn_context=cached_turn_context_for(chain_floor, baseline_turn),
            game_id=game_id,
            perspective=perspective,
            load_turn=cached_load,
            inference_materialization=resolved_inference_materialization,
        )
        emit_leg_progress(current_persisted, chain_floor)
        if turn_number == chain_floor:
            return current_persisted
        start_turn = chain_floor + 1

    if current_ledger is None:
        raise ConflictError(
            f"fleet snapshot chain for game {game_id} perspective {perspective} "
            f"player {player_id} turn {turn_number} has no ledger to advance from"
        )

    for materialize_turn in range(start_turn, turn_number + 1):
        require_prior_rst(
            materialize_turn,
            allow_missing_prior_rst=skip_missing_prefix_rst and materialize_turn == start_turn,
        )
        turn_info = require_turn(materialize_turn)
        current_persisted = _materialize_and_persist_player_turn(
            coherence,
            materialize_turn=materialize_turn,
            player_id=player_id,
            prior_persisted=current_persisted,
            prior_ledger=current_ledger,
            turn_info=turn_info,
            turn_context=cached_turn_context_for(materialize_turn, turn_info),
            game_id=game_id,
            perspective=perspective,
            load_turn=cached_load,
            inference_materialization=resolved_inference_materialization,
        )
        emit_leg_progress(current_persisted, materialize_turn)

    if current_persisted is None:
        raise ConflictError(
            f"fleet snapshot chain for game {game_id} perspective {perspective} "
            f"player {player_id} turn {turn_number} produced no persisted ledger"
        )
    return current_persisted


def _materialize_fleet_snapshot_chain(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Gap-fill fleet ledgers for every roster player through turn T.

    Temporary multi-turn path for roster snapshot / legacy ``compute_fleet``
    until REST compute migrates onto ensure (#204 out-of-scope). Not the
    player-scoped export ensure path -- see ``ensure_fleet_export``.
    """
    from api.errors import FleetGapFillEpochInvalidated

    turn_number = turn.settings.turn
    turn_context_cache: dict[int, FleetTurnContext] = {}
    try:
        for player_id in _roster_player_ids(turn):
            generation = persistence.player_invalidation_generation(
                game_id,
                perspective,
                player_id,
            )
            player_coherence = _GapFillCoherence(
                persistence,
                game_id,
                perspective,
                player_id,
                generation,
            )
            _materialize_fleet_ledger_chain_for_player(
                persistence,
                game_id,
                perspective,
                player_id,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                coherence=player_coherence,
                turn_context_cache=turn_context_cache,
            )
    except _FleetSnapshotInvalidated as exc:
        raise FleetGapFillEpochInvalidated(
            f"fleet snapshot gap-fill for game {game_id} perspective {perspective} "
            f"turn {turn_number} aborted: invalidation generation bumped mid-chain"
        ) from exc
    snapshot = persistence.get_snapshot(game_id, perspective, turn_number)
    if snapshot is None:
        raise ConflictError(
            f"fleet snapshot gap-fill produced no document for game {game_id} "
            f"perspective {perspective} turn {turn_number}"
        )
    return snapshot


def _resolve_leaf_prior_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn: TurnInfo,
) -> tuple[PersistedFleetLedger | None, FleetAcquisitionLedger]:
    """Prior for single-turn leaf materialize: baseline at floor, else final T-1.

    Multi-turn unwind belongs on ``ensure_fleet_export`` / orchestrator DAG, not
    this leaf.
    """
    turn_number = turn.settings.turn
    chain_floor = accelerated_ensure_floor(turn.settings, turn_number)
    if turn_number == chain_floor:
        return None, ensure_fleet_baseline_for_player(
            game_id,
            perspective,
            turn,
            player_id,
        )
    prior_turn = turn_number - 1
    prior = persistence.get_ledger(game_id, perspective, prior_turn, player_id)
    if prior is None or not prior.provenance.is_final:
        raise ConflictError(
            f"fleet leaf materialize for game {game_id} perspective {perspective} "
            f"player {player_id} turn {turn_number} requires a final prior ledger "
            f"at turn {prior_turn}; use ensure_fleet_export / orchestrator for "
            "multi-turn gap-fill"
        )
    return prior, prior.ledger


def get_or_materialize_fleet_ledger_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
    query_context: AnalyticQueryContext | None = None,
    on_progress: FleetMaterializationProgressCallback | None = None,
) -> PersistedFleetLedger:
    """Return a cached final ledger or materialize a single turn for one player.

    Cold multi-turn gap-fill belongs on ``ensure_fleet_export`` / orchestrator
    submit+wait. This leaf is cache-hit or one turn when prior is final (or
    baseline at the accelerated ensure floor). ``query_context`` is retained for
    call-site compatibility but does not nest ensure.
    """
    del query_context, on_progress
    from api.errors import FleetGapFillEpochInvalidated

    turn_number = turn.settings.turn
    cached = persistence.get_ledger(game_id, perspective, turn_number, player_id)
    if cached is not None and _is_fleet_ledger_cache_hit(cached):
        return cached

    prior_persisted, prior_ledger = _resolve_leaf_prior_for_player(
        persistence,
        game_id,
        perspective,
        player_id,
        turn,
    )
    generation = persistence.player_invalidation_generation(game_id, perspective, player_id)
    coherence = _GapFillCoherence(
        persistence,
        game_id,
        perspective,
        player_id,
        generation,
    )
    try:
        with gap_fill_coherence_scope(coherence):
            return _materialize_and_persist_player_turn(
                coherence,
                materialize_turn=turn_number,
                player_id=player_id,
                prior_persisted=prior_persisted,
                prior_ledger=prior_ledger,
                turn_info=turn,
                turn_context=FleetTurnContext.from_turn(turn),
                game_id=game_id,
                perspective=perspective,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
            )
    except _FleetSnapshotInvalidated as exc:
        raise FleetGapFillEpochInvalidated(
            f"fleet leaf materialize for game {game_id} perspective {perspective} "
            f"player {player_id} turn {turn_number} aborted: invalidation "
            "generation bumped mid-put"
        ) from exc


def get_or_materialize_fleet_snapshot(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
    query_context: AnalyticQueryContext | None = None,
) -> FleetTurnSnapshot:
    """Return a cached snapshot or multi-turn gap-fill for the full roster.

    Roster snapshot / legacy ``compute_fleet`` unwind via
    ``_materialize_fleet_snapshot_chain`` (temporary until REST compute migrates
    onto ensure -- #204 out-of-scope). Player-scoped leaf
    ``get_or_materialize_fleet_ledger_for_player`` remains single-turn.
    ``query_context`` is retained for call-site compatibility and does not nest
    ensure.
    """
    del query_context
    turn_number = turn.settings.turn
    cached = persistence.get_snapshot(game_id, perspective, turn_number)
    if cached is not None and _is_fleet_snapshot_cache_hit(
        persistence,
        game_id,
        perspective,
        turn_number,
        turn,
        cached,
    ):
        return cached

    return _materialize_fleet_snapshot_chain(
        persistence,
        game_id,
        perspective,
        turn,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )
