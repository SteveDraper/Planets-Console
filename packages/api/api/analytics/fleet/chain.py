"""Materialize fleet turn snapshots by chaining from prior turns."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.fleet.constants import ANALYTIC_ID, GAP_FILL_MAX_RETRIES
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.inferred_acquisition_ingest import (
    ingest_player_inferred_acquisitions,
    ingest_turn_inferred_acquisitions,
)
from api.analytics.fleet.materialization_provenance import resolve_fleet_materialization_provenance
from api.analytics.fleet.observation_ingest import (
    ingest_player_ship_observations,
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
from api.errors import ConflictError, NotFoundError, ValidationError
from api.models.game import TurnInfo


class _FleetSnapshotInvalidated(Exception):
    """Gap-fill observed a concurrent fleet snapshot invalidation."""


@dataclass
class _GapFillCoherence:
    """Guard gap-fill puts against concurrent fleet snapshot invalidation."""

    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    generation: int

    def put_ledger(
        self,
        turn_number: int,
        player_id: int,
        persisted: PersistedFleetLedger,
    ) -> None:
        self._assert_unchanged()
        self.persistence.put_ledger(
            self.game_id,
            self.perspective,
            turn_number,
            player_id,
            persisted,
        )
        self._assert_unchanged()

    def _assert_unchanged(self) -> None:
        if (
            self.persistence.invalidation_generation(self.game_id, self.perspective)
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
    *,
    baseline_turn_number: int | None = None,
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


def advance_ledger_to_turn(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
) -> FleetAcquisitionLedger:
    """Copy one player's ledger forward to shell turn T."""
    ledger = copy.deepcopy(prior_ledger)
    for player in iter_turn_players(turn):
        if player.id == ledger.player_id:
            ledger.player_name = player.username
            break
    return ledger


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


def apply_fleet_turn_delta_for_player(
    ledger: FleetAcquisitionLedger,
    turn_context: FleetTurnContext,
    *,
    game_id: int,
    perspective: int,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetAcquisitionLedger:
    """Apply turn-T fleet evidence deltas for one player ledger."""
    turn = turn_context.turn
    ingest_player_inferred_acquisitions(
        ledger,
        turn,
        game_id=game_id,
        perspective=perspective,
        inference_materialization=inference_materialization,
    )
    ingest_player_ship_observations(ledger, turn_context)
    return ledger


def _find_chain_anchor_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn_number: int,
) -> tuple[int, PersistedFleetLedger | None]:
    for prior_turn_number in range(turn_number - 1, 0, -1):
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
) -> int | None:
    """Return the lowest stored RST turn in ``1..turn_number``, if any."""
    for stored_turn_number in range(1, turn_number + 1):
        if load_turn(stored_turn_number) is not None:
            return stored_turn_number
    return None


def _roster_player_ids(turn: TurnInfo) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def _snapshot_has_all_roster_players(snapshot: FleetTurnSnapshot, turn: TurnInfo) -> bool:
    roster_ids = set(_roster_player_ids(turn))
    present_ids = {ledger.player_id for ledger in snapshot.players}
    return roster_ids <= present_ids


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
    coherence.put_ledger(materialize_turn, player_id, persisted)
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
    """Gap-fill one player's fleet ledger from the latest anchor through turn T."""
    turn_number = turn.settings.turn

    existing = persistence.get_ledger(game_id, perspective, turn_number, player_id)
    if existing is not None:
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

    def turn_context(materialize_turn: int, turn_info: TurnInfo) -> FleetTurnContext:
        if materialize_turn not in turn_context_cache:
            turn_context_cache[materialize_turn] = FleetTurnContext.from_turn(turn_info)
        return turn_context_cache[materialize_turn]

    def require_prior_rst(materialize_turn: int, *, allow_missing_prefix_rst: bool) -> None:
        if materialize_turn <= 1:
            return
        prior_turn_number = materialize_turn - 1
        if allow_missing_prefix_rst:
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
    )
    first_stored_rst = _first_stored_rst_turn(cached_load, turn_number)
    skip_missing_prefix_rst = (
        anchor_turn == 0
        and turn_number > 1
        and first_stored_rst is not None
        and first_stored_rst > 1
    )
    start_turn = anchor_turn + 1
    current_ledger = anchor_persisted.ledger if anchor_persisted is not None else None
    current_persisted = anchor_persisted

    if skip_missing_prefix_rst:
        start_turn = first_stored_rst
        assert first_stored_rst is not None
        first_rst_turn = require_turn(start_turn)
        current_ledger = advance_ledger_to_turn(
            ensure_fleet_baseline_for_player(
                game_id,
                perspective,
                first_rst_turn,
                player_id,
                baseline_turn_number=1,
            ),
            first_rst_turn,
        )
        current_persisted = None
    elif anchor_turn == 0:
        turn_one = require_turn(1)
        current_persisted = _materialize_and_persist_player_turn(
            coherence,
            materialize_turn=1,
            player_id=player_id,
            prior_persisted=None,
            prior_ledger=ensure_fleet_baseline_for_player(
                game_id,
                perspective,
                turn_one,
                player_id,
            ),
            turn_info=turn_one,
            turn_context=turn_context(1, turn_one),
            game_id=game_id,
            perspective=perspective,
            load_turn=cached_load,
            inference_materialization=resolved_inference_materialization,
        )
        current_ledger = current_persisted.ledger
        if turn_number == 1:
            return current_persisted
        start_turn = 2

    assert current_ledger is not None

    for materialize_turn in range(start_turn, turn_number + 1):
        require_prior_rst(
            materialize_turn,
            allow_missing_prefix_rst=skip_missing_prefix_rst and materialize_turn == start_turn,
        )
        turn_info = require_turn(materialize_turn)
        current_persisted = _materialize_and_persist_player_turn(
            coherence,
            materialize_turn=materialize_turn,
            player_id=player_id,
            prior_persisted=current_persisted,
            prior_ledger=current_ledger,
            turn_info=turn_info,
            turn_context=turn_context(materialize_turn, turn_info),
            game_id=game_id,
            perspective=perspective,
            load_turn=cached_load,
            inference_materialization=resolved_inference_materialization,
        )
        current_ledger = current_persisted.ledger

    assert current_persisted is not None
    return current_persisted


def _materialize_fleet_snapshot_chain(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
    coherence: _GapFillCoherence,
) -> FleetTurnSnapshot:
    """Gap-fill fleet ledgers for every roster player through turn T."""
    turn_context_cache: dict[int, FleetTurnContext] = {}
    for player_id in _roster_player_ids(turn):
        _materialize_fleet_ledger_chain_for_player(
            persistence,
            game_id,
            perspective,
            player_id,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            coherence=coherence,
            turn_context_cache=turn_context_cache,
        )
    snapshot = persistence.get_snapshot(game_id, perspective, turn.settings.turn)
    if snapshot is None:
        raise ConflictError(
            f"fleet snapshot gap-fill produced no document for game {game_id} "
            f"perspective {perspective} turn {turn.settings.turn}"
        )
    return snapshot


def get_or_materialize_fleet_ledger_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> PersistedFleetLedger:
    """Return a cached ledger or materialize turn T for one player."""
    turn_number = turn.settings.turn
    cached = persistence.get_ledger(game_id, perspective, turn_number, player_id)
    if cached is not None:
        return cached

    for attempt in range(GAP_FILL_MAX_RETRIES):
        coherence = _GapFillCoherence(
            persistence,
            game_id,
            perspective,
            persistence.invalidation_generation(game_id, perspective),
        )
        turn_context_cache: dict[int, FleetTurnContext] = {}
        try:
            return _materialize_fleet_ledger_chain_for_player(
                persistence,
                game_id,
                perspective,
                player_id,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                coherence=coherence,
                turn_context_cache=turn_context_cache,
            )
        except _FleetSnapshotInvalidated:
            cached_after_invalidation = persistence.get_ledger(
                game_id,
                perspective,
                turn_number,
                player_id,
            )
            if cached_after_invalidation is not None:
                return cached_after_invalidation
            if attempt + 1 >= GAP_FILL_MAX_RETRIES:
                break
            continue

    cached_after_retries = persistence.get_ledger(
        game_id,
        perspective,
        turn_number,
        player_id,
    )
    if cached_after_retries is not None:
        return cached_after_retries

    raise ConflictError(
        f"fleet ledger gap-fill for game {game_id} perspective {perspective} "
        f"player {player_id} turn {turn_number} exceeded {GAP_FILL_MAX_RETRIES} "
        "invalidation retries"
    )


def get_or_materialize_fleet_snapshot(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetTurnSnapshot:
    """Return a cached snapshot or materialize turn T from T-1 plus turn-T delta."""
    turn_number = turn.settings.turn
    cached = persistence.get_snapshot(game_id, perspective, turn_number)
    if cached is not None and _snapshot_has_all_roster_players(cached, turn):
        return cached

    for attempt in range(GAP_FILL_MAX_RETRIES):
        coherence = _GapFillCoherence(
            persistence,
            game_id,
            perspective,
            persistence.invalidation_generation(game_id, perspective),
        )
        try:
            return _materialize_fleet_snapshot_chain(
                persistence,
                game_id,
                perspective,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                coherence=coherence,
            )
        except _FleetSnapshotInvalidated:
            cached_after_invalidation = persistence.get_snapshot(
                game_id,
                perspective,
                turn_number,
            )
            if cached_after_invalidation is not None and _snapshot_has_all_roster_players(
                cached_after_invalidation, turn
            ):
                return cached_after_invalidation
            if attempt + 1 >= GAP_FILL_MAX_RETRIES:
                break
            continue

    cached_after_retries = persistence.get_snapshot(game_id, perspective, turn_number)
    if cached_after_retries is not None and _snapshot_has_all_roster_players(
        cached_after_retries,
        turn,
    ):
        return cached_after_retries

    raise ConflictError(
        f"fleet snapshot gap-fill for game {game_id} perspective {perspective} "
        f"turn {turn_number} exceeded {GAP_FILL_MAX_RETRIES} invalidation retries"
    )
