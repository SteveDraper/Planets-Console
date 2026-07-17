"""Read, write, and invalidate fleet turn snapshots."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    FLEET_LEDGERS_KEY,
    FLEET_MATERIALIZATION_VERSION,
)
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.fleet.serialization import (
    fleet_materialization_version_from_json,
    fleet_turn_snapshot_from_json,
    fleet_turn_snapshot_to_json,
    is_current_fleet_materialization_version,
    is_legacy_fleet_turn_document,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
    upgrade_legacy_fleet_turn_document,
)
from api.analytics.fleet.types import (
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend

OnSnapshotPersistedCallback = Callable[[int, int, int], None]
OnLedgerPersistedCallback = Callable[[FleetLedgerPersistedEvent], None]
DeferredNotification = Callable[[], None]


class FleetSnapshotPersistenceService:
    """Persist fleet acquisition ledgers at turn-scoped analytic breakpoints.

    Logical document path:
    ``games/{gameId}/{perspective}/turns/{turn}/analytics/fleet``

    In-document keys: ``ledgers/{playerId}`` -- each entry is one
    **fleet acquisition ledger** plus **fleet materialization provenance** and
    ``materializationVersion``.

    Scores-invalidation coupling (F2.x): when scores inference evidence updates
    for player P at host turn *H*, ``InferenceInvalidationService`` drops P's
    ledgers at fleet turns ``>= H`` via ``invalidate_player_ledgers_from_turn``.
    Turn document replace at *T* clears all players via
    ``invalidate_for_turn_write``. Scores pair-aware invalidation (turn *T* and
    *T-1*) is independent of fleet invalidation; both scores hooks run from
    ``on_turn_stored`` today.

    **Invalidation generation:** Each ``(game_id, perspective, player_id)`` scope has a
    monotonic counter bumped when that player's fleet ledgers are invalidated.
    Gap-fill coordinators record the generation at chain start and abort (then retry
    from a fresh anchor) when the counter advances during multi-turn materialization.
    Per-player scores invalidation bumps only the target player; turn document replace
    bumps every player who had ledgers dropped at affected turns. Invalidation does not
    block on gap-fill; concurrent invalidation callbacks only bump counters and delete
    stored snapshots. ``put_snapshot`` does not bump invalidation generation; per-player
    counters advance only on read-time stale pruning, legacy document delete, and
    explicit invalidation methods (``invalidate_for_turn_write``,
    ``invalidate_player_ledgers_from_turn``).

    **Materialization version:** Each persisted ledger entry carries
    ``materializationVersion`` (see ``FLEET_MATERIALIZATION_VERSION``). On read,
    mismatched or missing versions are deleted and treated as cache misses for that
    player so deploys that change materialization semantics re-chain without a turn
    reload.
    """

    def __init__(
        self,
        storage: StorageBackend,
        *,
        on_snapshot_persisted: OnSnapshotPersistedCallback | None = None,
        on_ledger_persisted: OnLedgerPersistedCallback | None = None,
    ) -> None:
        self._storage = storage
        self._on_snapshot_persisted = on_snapshot_persisted
        self._on_ledger_persisted = on_ledger_persisted
        # Player-scoped: fleet compute / gap-fill coherence across turns.
        self._invalidation_generation: dict[tuple[int, int, int], int] = {}
        # Turn-scoped: scores@N epoch tracks fleet@(N-1) only.
        self._turn_invalidation_generation: dict[tuple[int, int, int, int], int] = {}
        self._generation_lock = threading.Lock()

    @staticmethod
    def document_key(game_id: int, perspective: int, turn_number: int) -> str:
        return f"games/{game_id}/{perspective}/turns/{turn_number}/analytics/{ANALYTIC_ID}"

    def get_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> PersistedFleetLedger | None:
        document = self._load_document(game_id, perspective, turn_number)
        if document is None:
            return None
        ledger_wire = self._ledger_wire_from_document(document, player_id)
        if ledger_wire is None:
            return None
        persisted = persisted_fleet_ledger_from_json(ledger_wire)
        if not is_current_fleet_materialization_version(persisted.materialization_version):
            self._delete_ledger_entry(game_id, perspective, turn_number, player_id)
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                player_id,
                (turn_number,),
            )
            return None
        return persisted

    def put_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted: PersistedFleetLedger,
        *,
        defer_ledger_persisted_notification: bool = False,
    ) -> DeferredNotification | None:
        if persisted.ledger.player_id != player_id:
            raise ValidationError(
                "persisted fleet ledger player_id "
                f"{persisted.ledger.player_id} does not match key player_id {player_id}",
            )
        to_store = PersistedFleetLedger(
            ledger=persisted.ledger,
            provenance=persisted.provenance,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        )
        prior = self._prior_ledger_for_notification(
            game_id,
            perspective,
            turn_number,
            player_id,
        )
        document = self._load_or_create_document(game_id, perspective, turn_number)
        ledgers = self._ledgers_object(document)
        ledgers[str(player_id)] = persisted_fleet_ledger_to_json(to_store)
        self._write_document(game_id, perspective, turn_number, document)
        notification = self._ledger_persisted_notification_if_needed(
            game_id,
            perspective,
            turn_number,
            player_id,
            prior=prior,
            persisted=to_store,
        )
        if defer_ledger_persisted_notification:
            return notification
        if notification is not None:
            notification()
        return None

    def has_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> bool:
        """Return whether a usable fleet ledger is stored for this player scope.

        Delegates to ``get_ledger`` -- not a cheap key-exists probe. A call may
        upgrade legacy monolithic documents to the ``ledgers/`` layout, delete
        stale ledger entries, write storage, and bump invalidation generation
        when stale data is removed.
        """
        return self.get_ledger(game_id, perspective, turn_number, player_id) is not None

    def has_final_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> bool:
        persisted = self.get_ledger(game_id, perspective, turn_number, player_id)
        return persisted is not None and persisted.provenance.is_final

    def delete_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> None:
        self._delete_ledger_entry(game_id, perspective, turn_number, player_id)

    def list_ledger_player_ids(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> list[int]:
        document = self._load_document(game_id, perspective, turn_number)
        if document is None:
            return []
        ledgers = self._ledgers_object(document)
        player_ids: list[int] = []
        for player_key in ledgers:
            if not player_key.isdigit():
                continue
            player_ids.append(int(player_key))
        return sorted(player_ids)

    def get_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> FleetTurnSnapshot | None:
        document = self._load_document(game_id, perspective, turn_number)
        if document is None:
            return None
        if not self._prune_stale_ledgers(game_id, perspective, turn_number, document):
            return None
        if not self._ledgers_object(document):
            self.delete_snapshot(game_id, perspective, turn_number)
            return None
        snapshot = fleet_turn_snapshot_from_json(document)
        snapshot.materialization_version = FLEET_MATERIALIZATION_VERSION
        return snapshot

    def has_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> bool:
        """Return whether a usable fleet turn snapshot is stored for this scope.

        Delegates to ``get_snapshot`` -- not a cheap key-exists probe. A call may
        validate wire shape, upgrade legacy monolithic documents to the
        ``ledgers/`` layout, prune stale per-player ledger entries, delete the
        turn document when nothing usable remains, write storage, and bump
        invalidation generation when stale data is removed.
        """
        return self.get_snapshot(game_id, perspective, turn_number) is not None

    def put_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        snapshot: FleetTurnSnapshot,
    ) -> None:
        snapshot.materialization_version = FLEET_MATERIALIZATION_VERSION
        if snapshot.game_id != game_id:
            raise ValidationError(
                f"fleet snapshot game_id {snapshot.game_id} does not match key game_id {game_id}"
            )
        if snapshot.perspective != perspective:
            raise ValidationError(
                "fleet snapshot perspective "
                f"{snapshot.perspective} does not match key perspective {perspective}"
            )
        if snapshot.turn != turn_number:
            raise ValidationError(
                f"fleet snapshot turn {snapshot.turn} does not match key turn_number {turn_number}"
            )
        self._write_document(
            game_id,
            perspective,
            turn_number,
            fleet_turn_snapshot_to_json(snapshot),
        )
        self._notify_snapshot_persisted_legacy(game_id, perspective, turn_number)

    def _prior_ledger_for_notification(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> PersistedFleetLedger | None:
        document = self._load_document(game_id, perspective, turn_number)
        if document is None:
            return None
        ledger_wire = self._ledger_wire_from_document(document, player_id)
        if ledger_wire is None:
            return None
        return persisted_fleet_ledger_from_json(ledger_wire)

    def _notify_ledger_persisted_if_needed(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        *,
        prior: PersistedFleetLedger | None,
        persisted: PersistedFleetLedger,
    ) -> None:
        notification = self._ledger_persisted_notification_if_needed(
            game_id,
            perspective,
            turn_number,
            player_id,
            prior=prior,
            persisted=persisted,
        )
        if notification is not None:
            notification()

    def _ledger_persisted_notification_if_needed(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        *,
        prior: PersistedFleetLedger | None,
        persisted: PersistedFleetLedger,
    ) -> DeferredNotification | None:
        callback = self._on_ledger_persisted
        if callback is None:
            return None
        if not persisted.provenance.is_final:
            return None
        if prior is None or not prior.provenance.is_final:
            return lambda: self._dispatch_ledger_persisted(
                game_id,
                perspective,
                turn_number,
                player_id,
                persisted=persisted,
            )
        if prior.materialization_version != persisted.materialization_version:
            return lambda: self._dispatch_ledger_persisted(
                game_id,
                perspective,
                turn_number,
                player_id,
                persisted=persisted,
            )
        return None

    def _dispatch_ledger_persisted(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        *,
        persisted: PersistedFleetLedger,
    ) -> None:
        callback = self._on_ledger_persisted
        if callback is None:
            return
        callback(
            FleetLedgerPersistedEvent(
                game_id=game_id,
                perspective=perspective,
                fleet_turn=turn_number,
                player_id=player_id,
                materialization_version=persisted.materialization_version,
            )
        )

    def _notify_snapshot_persisted_legacy(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> None:
        """Invoke legacy roster-level callback after explicit ``put_snapshot`` only."""
        if self._on_snapshot_persisted is None:
            return
        self._on_snapshot_persisted(game_id, perspective, turn_number)

    @property
    def on_snapshot_persisted(self) -> OnSnapshotPersistedCallback | None:
        """Legacy roster-level callback; production wiring uses ``on_ledger_persisted``."""
        return self._on_snapshot_persisted

    @on_snapshot_persisted.setter
    def on_snapshot_persisted(self, callback: OnSnapshotPersistedCallback | None) -> None:
        self._on_snapshot_persisted = callback

    @property
    def on_ledger_persisted(self) -> OnLedgerPersistedCallback | None:
        return self._on_ledger_persisted

    @on_ledger_persisted.setter
    def on_ledger_persisted(self, callback: OnLedgerPersistedCallback | None) -> None:
        self._on_ledger_persisted = callback

    def delete_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> None:
        try:
            self._storage.delete(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            pass

    def player_invalidation_generation(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> int:
        """Return the player-scoped epoch used by fleet compute and gap-fill."""
        with self._generation_lock:
            return self._invalidation_generation.get((game_id, perspective, player_id), 0)

    def turn_invalidation_generation(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn: int,
    ) -> int:
        """Return the turn-scoped epoch that scores@N reads for prior fleet@(N-1)."""
        with self._generation_lock:
            return self._turn_invalidation_generation.get(
                (game_id, perspective, player_id, turn),
                0,
            )

    def invalidate_for_turn_write(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> set[int]:
        """Drop fleet snapshots at turns >= turn_number for one perspective."""

        cleared: set[int] = set()
        cleared_player_ids: set[int] = set()
        for stored_turn in self._iter_stored_turns_from(game_id, perspective, turn_number):
            # Turn replace deletes whole documents; raw read avoids legacy upgrade side effects.
            document = self._read_document_raw(game_id, perspective, stored_turn)
            if document is None:
                continue
            player_ids = self._player_ids_in_document(document)
            if not player_ids:
                continue
            self.delete_snapshot(game_id, perspective, stored_turn)
            cleared.add(stored_turn)
            cleared_player_ids.update(player_ids)
        for cleared_player_id in cleared_player_ids:
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                cleared_player_id,
                cleared,
            )
        return cleared

    def invalidate_player_ledgers_from_turn(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> set[int]:
        """Drop one player's fleet ledgers at turns >= turn_number for one perspective."""

        def invalidate_turn(stored_turn: int) -> bool:
            # Per-player delete may upgrade legacy layout before removing one ledger entry.
            document = self._load_document(game_id, perspective, stored_turn)
            if document is None:
                return False
            ledgers = self._ledgers_object(document)
            if str(player_id) not in ledgers:
                return False
            self._delete_ledger_entry(game_id, perspective, stored_turn, player_id)
            return True

        cleared: set[int] = set()
        for stored_turn in self._iter_stored_turns_from(game_id, perspective, turn_number):
            if invalidate_turn(stored_turn):
                cleared.add(stored_turn)
        if cleared:
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                player_id,
                cleared,
            )
        return cleared

    def bump_player_invalidation_generation(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> None:
        """Advance the player-scoped materialization epoch."""
        with self._generation_lock:
            player_key = (game_id, perspective, player_id)
            self._invalidation_generation[player_key] = (
                self._invalidation_generation.get(player_key, 0) + 1
            )

    def bump_turn_invalidation_generation(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn: int,
    ) -> None:
        """Advance the turn-scoped materialization epoch for one fleet turn."""
        with self._generation_lock:
            turn_key = (game_id, perspective, player_id, turn)
            self._turn_invalidation_generation[turn_key] = (
                self._turn_invalidation_generation.get(turn_key, 0) + 1
            )

    def bump_player_and_turn_invalidations(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turns: Iterable[int],
    ) -> None:
        """Bump player epoch once and each turn epoch under a single lock."""
        with self._generation_lock:
            player_key = (game_id, perspective, player_id)
            self._invalidation_generation[player_key] = (
                self._invalidation_generation.get(player_key, 0) + 1
            )
            for turn in turns:
                turn_key = (game_id, perspective, player_id, turn)
                self._turn_invalidation_generation[turn_key] = (
                    self._turn_invalidation_generation.get(turn_key, 0) + 1
                )

    def _read_document_raw(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object] | None:
        try:
            data = self._storage.get(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("stored fleet turn snapshot must be a JSON object")
        return data

    def _load_document(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object] | None:
        data = self._read_document_raw(game_id, perspective, turn_number)
        if data is None:
            return None
        if is_legacy_fleet_turn_document(data):
            if not is_current_fleet_materialization_version(
                fleet_materialization_version_from_json(data),
            ):
                player_ids = self._player_ids_in_document(data)
                self.delete_snapshot(game_id, perspective, turn_number)
                for document_player_id in player_ids:
                    self.bump_player_and_turn_invalidations(
                        game_id,
                        perspective,
                        document_player_id,
                        (turn_number,),
                    )
                return None
            upgraded = upgrade_legacy_fleet_turn_document(data)
            self._write_document(game_id, perspective, turn_number, upgraded)
            return upgraded
        return data

    def _load_or_create_document(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        document = self._load_document(game_id, perspective, turn_number)
        if document is not None:
            return document
        return {
            "analyticId": ANALYTIC_ID,
            "gameId": game_id,
            "perspective": perspective,
            "turn": turn_number,
            FLEET_LEDGERS_KEY: {},
        }

    def _write_document(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        document: dict[str, object],
    ) -> None:
        self._storage.put(self.document_key(game_id, perspective, turn_number), document)

    @staticmethod
    def _ledgers_object(document: dict[str, object]) -> dict[str, object]:
        ledgers = document.setdefault(FLEET_LEDGERS_KEY, {})
        if not isinstance(ledgers, dict):
            raise ValidationError("fleet turn snapshot ledgers must be an object")
        return ledgers

    def _ledger_wire_from_document(
        self,
        document: dict[str, object],
        player_id: int,
    ) -> dict[str, object] | None:
        ledgers = self._ledgers_object(document)
        ledger_wire = ledgers.get(str(player_id))
        if ledger_wire is None:
            return None
        if not isinstance(ledger_wire, dict):
            raise ValidationError("persisted fleet ledger must be an object")
        return ledger_wire

    def _delete_ledger_entry(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> None:
        document = self._read_document_raw(game_id, perspective, turn_number)
        if document is None:
            return
        ledgers = self._ledgers_object(document)
        ledgers.pop(str(player_id), None)
        if ledgers:
            self._write_document(game_id, perspective, turn_number, document)
            return
        self.delete_snapshot(game_id, perspective, turn_number)

    def _prune_stale_ledgers(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        document: dict[str, object],
    ) -> bool:
        ledgers = self._ledgers_object(document)
        stale_player_ids: list[int] = []
        for player_key, ledger_wire in list(ledgers.items()):
            if not player_key.isdigit() or not isinstance(ledger_wire, dict):
                continue
            version = fleet_materialization_version_from_json(ledger_wire)
            if is_current_fleet_materialization_version(version):
                continue
            stale_player_ids.append(int(player_key))
        if not stale_player_ids:
            return True
        for player_id in stale_player_ids:
            ledgers.pop(str(player_id), None)
        if ledgers:
            self._write_document(game_id, perspective, turn_number, document)
        else:
            self.delete_snapshot(game_id, perspective, turn_number)
        for stale_player_id in stale_player_ids:
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                stale_player_id,
                (turn_number,),
            )
        return False

    @staticmethod
    def _player_ids_in_document(document: dict[str, object]) -> list[int]:
        player_ids: list[int] = []
        ledgers = document.get(FLEET_LEDGERS_KEY)
        if isinstance(ledgers, dict):
            for player_key in ledgers:
                if player_key.isdigit():
                    player_ids.append(int(player_key))
        players = document.get("players")
        if isinstance(players, list):
            for player_wire in players:
                if not isinstance(player_wire, dict):
                    continue
                player_id = player_wire.get("playerId")
                if isinstance(player_id, int):
                    player_ids.append(player_id)
        return sorted(set(player_ids))

    def _iter_stored_turns_from(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> Iterator[int]:
        """Yield stored fleet turn numbers at or after ``turn_number``."""

        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn >= turn_number:
                yield stored_turn

    def _stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        turns_prefix = f"games/{game_id}/{perspective}/turns"
        try:
            segments = self._storage.list(turns_prefix)
        except NotFoundError, ValidationError:
            return []
        turn_numbers: list[int] = []
        for segment in segments:
            if segment.isdigit():
                turn_numbers.append(int(segment))
        return sorted(turn_numbers)
