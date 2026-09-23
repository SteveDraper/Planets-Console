"""Read, write, and invalidate fleet turn snapshots."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator

from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    FLEET_EVIDENCE_MARK_SEGMENT,
    FLEET_LEDGERS_KEY,
    FLEET_MATERIALIZATION_VERSION,
)
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.fleet.serialization import (
    fleet_evidence_mark_from_json,
    fleet_evidence_mark_to_json,
    fleet_ledger_is_ensure_final,
    fleet_materialization_version_from_json,
    is_current_fleet_materialization_version,
    is_legacy_fleet_turn_document,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
    upgrade_legacy_fleet_turn_document,
)
from api.analytics.fleet.types import (
    FleetEvidenceMark,
    FleetMaterializationProvenance,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend

OnSnapshotPersistedCallback = Callable[[int, int, int], None]
OnLedgerPersistedCallback = Callable[[FleetLedgerPersistedEvent], None]
DeferredNotification = Callable[[], None]

_ABSENT_EVIDENCE_MARK = FleetEvidenceMark()


class FleetSnapshotPersistenceService:
    """Persist one fleet acquisition ledger file per player per turn.

    Ledger path:
    ``games/{gameId}/{perspective}/turns/{turn}/analytics/fleet/{playerId}``

    Each file is that player's ledger, provenance, materialization version, and
    the evidence generation it was written under. Other players in the turn are
    not read or rewritten.

    Evidence mark path:
    ``games/{gameId}/{perspective}/analytics/fleet-evidence/{playerId}``

    The mark is one small document per ``(game, perspective, player)``. A durable
    scores-evidence update bumps its generation and does not open ledger files.
    A ledger at turn T is ensure-final only when it exists, provenance is
    ``(true, true)``, the materialization version is current, and either T is
    before the mark's ``appliesFromTurn`` or the ledger's generation equals the
    mark. Held-solution admission bumps the in-memory epoch only.

    A legacy shared turn document at ``.../analytics/fleet`` is split into
    per-player files on read, then removed.

    **Invalidation generation:** Each ``(game_id, perspective, player_id)`` scope
    has an in-memory counter bumped when that player's fleet work must abort.
    Gap-fill coordinators record it at chain start. Turn-scoped counters let
    ``scores@N`` track ``fleet@(N-1)`` only. ``put_ledger`` does not bump them.
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
        self._evidence_marks: dict[tuple[int, int, int], FleetEvidenceMark] = {}
        self._known_ledger_turns: dict[tuple[int, int, int], set[int]] = {}
        self._legacy_absent: set[tuple[int, int, int]] = set()
        self._generation_lock = threading.Lock()

    @staticmethod
    def document_key(game_id: int, perspective: int, turn_number: int) -> str:
        """Legacy shared turn document, split into per-player files on read."""
        return f"games/{game_id}/{perspective}/turns/{turn_number}/analytics/{ANALYTIC_ID}"

    @staticmethod
    def ledger_key(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> str:
        return (
            f"games/{game_id}/{perspective}/turns/{turn_number}/analytics/{ANALYTIC_ID}/{player_id}"
        )

    @staticmethod
    def evidence_mark_key(game_id: int, perspective: int, player_id: int) -> str:
        return f"games/{game_id}/{perspective}/analytics/{FLEET_EVIDENCE_MARK_SEGMENT}/{player_id}"

    def get_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> PersistedFleetLedger | None:
        persisted = self._read_player_ledger(game_id, perspective, turn_number, player_id)
        if persisted is not None:
            return persisted
        if not self._migrate_legacy_turn_document(game_id, perspective, turn_number):
            return None
        return self._read_player_ledger(game_id, perspective, turn_number, player_id)

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
        prior = self._read_player_ledger(game_id, perspective, turn_number, player_id)
        if prior is None and self._migrate_legacy_turn_document(
            game_id,
            perspective,
            turn_number,
        ):
            prior = self._read_player_ledger(game_id, perspective, turn_number, player_id)
        mark = self.evidence_mark(game_id, perspective, player_id)
        to_store = PersistedFleetLedger(
            ledger=persisted.ledger,
            provenance=persisted.provenance,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
            evidence_generation=mark.evidence_generation,
        )
        prior_was_ensure_final = prior is not None and self.ledger_is_ensure_final(
            game_id,
            perspective,
            turn_number,
            player_id,
            prior,
        )
        self._write_player_ledger(game_id, perspective, turn_number, player_id, to_store)
        self._remember_ledger_turn(game_id, perspective, player_id, turn_number)
        if to_store.provenance.is_final:
            self._advance_evidence_mark_after_boundary_write(
                game_id,
                perspective,
                player_id,
                turn_number,
                to_store.evidence_generation,
            )
        notification = self._ledger_persisted_notification_if_needed(
            game_id,
            perspective,
            turn_number,
            player_id,
            prior=prior,
            prior_was_ensure_final=prior_was_ensure_final,
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

        Delegates to ``get_ledger``. A call may split a legacy shared document,
        delete a stale-version file, and bump the in-memory invalidation epoch.
        """
        return self.get_ledger(game_id, perspective, turn_number, player_id) is not None

    def ledger_is_ensure_final(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted: PersistedFleetLedger,
    ) -> bool:
        return fleet_ledger_is_ensure_final(
            persisted,
            turn_number=turn_number,
            mark=self.evidence_mark(game_id, perspective, player_id),
        )

    def has_final_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> bool:
        persisted = self.get_ledger(game_id, perspective, turn_number, player_id)
        if persisted is None:
            return False
        return self.ledger_is_ensure_final(
            game_id,
            perspective,
            turn_number,
            player_id,
            persisted,
        )

    def delete_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> None:
        self._unlink_player_ledger(game_id, perspective, turn_number, player_id)
        self._forget_ledger_turn(game_id, perspective, player_id, turn_number)

    def list_ledger_player_ids(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> list[int]:
        self._migrate_legacy_turn_document(game_id, perspective, turn_number)
        return self._list_player_ids(game_id, perspective, turn_number)

    def get_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> FleetTurnSnapshot | None:
        player_ids = self.list_ledger_player_ids(game_id, perspective, turn_number)
        players = []
        for player_id in player_ids:
            persisted = self.get_ledger(game_id, perspective, turn_number, player_id)
            if persisted is not None:
                players.append(persisted.ledger)
        if not players:
            return None
        return FleetTurnSnapshot(
            analytic_id=ANALYTIC_ID,
            game_id=game_id,
            perspective=perspective,
            turn=turn_number,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
            players=players,
        )

    def has_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> bool:
        """Return whether any usable fleet ledger is stored for this turn."""
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
        for player_ledger in snapshot.players:
            self.put_ledger(
                game_id,
                perspective,
                turn_number,
                player_ledger.player_id,
                PersistedFleetLedger(
                    ledger=player_ledger,
                    provenance=FleetMaterializationProvenance(),
                    materialization_version=FLEET_MATERIALIZATION_VERSION,
                ),
            )
        self._notify_snapshot_persisted_legacy(game_id, perspective, turn_number)

    def delete_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> None:
        for player_id in self._list_player_ids(game_id, perspective, turn_number):
            self._unlink_player_ledger(game_id, perspective, turn_number, player_id)
            self._forget_ledger_turn(game_id, perspective, player_id, turn_number)
        self._delete_legacy_document(game_id, perspective, turn_number)

    def evidence_mark(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> FleetEvidenceMark:
        key = (game_id, perspective, player_id)
        with self._generation_lock:
            cached = self._evidence_marks.get(key)
            if cached is not None:
                return cached
            loaded = self._read_evidence_mark(game_id, perspective, player_id)
            raced = self._evidence_marks.get(key)
            if raced is not None:
                return raced
            self._evidence_marks[key] = loaded
            return loaded

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
        """Drop fleet ledger files at turns >= turn_number for one perspective."""

        cleared: set[int] = set()
        cleared_player_ids: set[int] = set()
        for stored_turn in self._iter_stored_turns_from(game_id, perspective, turn_number):
            player_ids = self._player_ids_for_turn_replace(game_id, perspective, stored_turn)
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
        *,
        durable: bool = False,
    ) -> set[int]:
        """Mark player P's fleet ledgers stale from ``turn_number`` without file walks.

        Always bumps the in-memory epoch so in-flight fleet work for P aborts.
        When ``durable`` is true, also bumps P's evidence mark. Ledger files stay
        in place. The returned turns are the host turn plus turns this process
        has already read or written at or after ``turn_number``, for stream wake.
        """
        if durable:
            self._bump_durable_evidence_mark(
                game_id,
                perspective,
                player_id,
                turn_number,
            )
        turns = self._known_turns_from(game_id, perspective, player_id, turn_number)
        self.bump_player_and_turn_invalidations(
            game_id,
            perspective,
            player_id,
            turns,
        )
        return turns

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

    def delete_evidence_mark(self, game_id: int, perspective: int, player_id: int) -> bool:
        """Remove one player's evidence mark. Return whether a file was deleted."""
        deleted = self._delete_if_present(
            self.evidence_mark_key(game_id, perspective, player_id),
        )
        with self._generation_lock:
            self._evidence_marks.pop((game_id, perspective, player_id), None)
        return deleted

    def delete_evidence_marks(self, game_id: int, perspective: int) -> list[str]:
        """Remove every evidence mark for one perspective. Return deleted keys."""
        prefix = f"games/{game_id}/{perspective}/analytics/{FLEET_EVIDENCE_MARK_SEGMENT}"
        deleted: list[str] = []
        for segment in self._list_segments(prefix):
            if not segment.isdigit():
                continue
            player_id = int(segment)
            key = self.evidence_mark_key(game_id, perspective, player_id)
            if self.delete_evidence_mark(game_id, perspective, player_id):
                deleted.append(key)
        return deleted

    def _ledger_persisted_notification_if_needed(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        *,
        prior: PersistedFleetLedger | None,
        prior_was_ensure_final: bool,
        persisted: PersistedFleetLedger,
    ) -> DeferredNotification | None:
        callback = self._on_ledger_persisted
        if callback is None:
            return None
        if not persisted.provenance.is_final:
            return None
        generation_changed = (
            prior is not None and prior.evidence_generation != persisted.evidence_generation
        )
        version_changed = (
            prior is not None and prior.materialization_version != persisted.materialization_version
        )
        if prior_was_ensure_final and not generation_changed and not version_changed:
            return None
        return lambda: self._dispatch_ledger_persisted(
            game_id,
            perspective,
            turn_number,
            player_id,
            persisted=persisted,
        )

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

    def _bump_durable_evidence_mark(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        host_turn: int,
    ) -> FleetEvidenceMark:
        """Advance the mark. Do not move ``appliesFromTurn`` forward over a gap."""
        with self._generation_lock:
            current = self._evidence_marks.get((game_id, perspective, player_id))
            if current is None:
                current = self._read_evidence_mark(game_id, perspective, player_id)
            applies_from = current.applies_from_turn
            if applies_from is None or host_turn < applies_from:
                applies_from = host_turn
            updated = FleetEvidenceMark(
                evidence_generation=current.evidence_generation + 1,
                applies_from_turn=applies_from,
            )
            self._write_evidence_mark(game_id, perspective, player_id, updated)
            self._evidence_marks[(game_id, perspective, player_id)] = updated
            return updated

    def _advance_evidence_mark_after_boundary_write(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn_number: int,
        evidence_generation: int,
    ) -> None:
        """After a final ledger at the bound, the next turn is the new bound.

        The generation is unchanged. A crash before this write leaves the bound
        on the turn just stored; that ledger still matches the generation, and
        later turns do not.
        """
        with self._generation_lock:
            key = (game_id, perspective, player_id)
            current = self._evidence_marks.get(key)
            if current is None:
                current = self._read_evidence_mark(game_id, perspective, player_id)
            if current.applies_from_turn != turn_number:
                return
            if current.evidence_generation != evidence_generation:
                return
            updated = FleetEvidenceMark(
                evidence_generation=current.evidence_generation,
                applies_from_turn=turn_number + 1,
            )
            self._write_evidence_mark(game_id, perspective, player_id, updated)
            self._evidence_marks[key] = updated

    def _read_evidence_mark(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> FleetEvidenceMark:
        data = self._read_json_object(self.evidence_mark_key(game_id, perspective, player_id))
        if data is None:
            return _ABSENT_EVIDENCE_MARK
        return fleet_evidence_mark_from_json(data)

    def _write_evidence_mark(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        mark: FleetEvidenceMark,
    ) -> None:
        self._storage.put(
            self.evidence_mark_key(game_id, perspective, player_id),
            fleet_evidence_mark_to_json(mark),
        )

    def _read_player_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> PersistedFleetLedger | None:
        data = self._read_json_object(
            self.ledger_key(game_id, perspective, turn_number, player_id),
        )
        if data is None:
            return None
        persisted = persisted_fleet_ledger_from_json(data)
        if not is_current_fleet_materialization_version(persisted.materialization_version):
            self._unlink_player_ledger(game_id, perspective, turn_number, player_id)
            self._forget_ledger_turn(game_id, perspective, player_id, turn_number)
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                player_id,
                (turn_number,),
            )
            return None
        self._remember_ledger_turn(game_id, perspective, player_id, turn_number)
        return persisted

    def _write_player_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted: PersistedFleetLedger,
    ) -> None:
        self._storage.put(
            self.ledger_key(game_id, perspective, turn_number, player_id),
            persisted_fleet_ledger_to_json(persisted),
        )

    def _unlink_player_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> None:
        self._delete_if_present(self.ledger_key(game_id, perspective, turn_number, player_id))

    def _migrate_legacy_turn_document(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> bool:
        key = (game_id, perspective, turn_number)
        if key in self._legacy_absent:
            return False
        data = self._read_json_object(self.document_key(game_id, perspective, turn_number))
        if data is None:
            self._legacy_absent.add(key)
            return False
        if not is_legacy_fleet_turn_document(data) and FLEET_LEDGERS_KEY not in data:
            self._legacy_absent.add(key)
            return False
        if is_legacy_fleet_turn_document(data):
            if not is_current_fleet_materialization_version(
                fleet_materialization_version_from_json(data),
            ):
                player_ids = self._player_ids_in_document(data)
                self._delete_legacy_document(game_id, perspective, turn_number)
                self._legacy_absent.add(key)
                for document_player_id in player_ids:
                    self.bump_player_and_turn_invalidations(
                        game_id,
                        perspective,
                        document_player_id,
                        (turn_number,),
                    )
                return False
            data = upgrade_legacy_fleet_turn_document(data)
        ledgers = data.get(FLEET_LEDGERS_KEY, {})
        wires: list[tuple[int, dict[str, object]]] = []
        stale_player_ids: list[int] = []
        if isinstance(ledgers, dict):
            for player_key, ledger_wire in ledgers.items():
                if not player_key.isdigit() or not isinstance(ledger_wire, dict):
                    continue
                player_id = int(player_key)
                if not is_current_fleet_materialization_version(
                    fleet_materialization_version_from_json(ledger_wire),
                ):
                    stale_player_ids.append(player_id)
                    continue
                wire = dict(ledger_wire)
                wire.setdefault("evidenceGeneration", 0)
                wires.append((player_id, wire))
        # Delete the shared document before writing player files so an in-memory
        # tree does not store those files inside the legacy object.
        self._delete_legacy_document(game_id, perspective, turn_number)
        self._legacy_absent.add(key)
        for player_id, wire in wires:
            self._storage.put(
                self.ledger_key(game_id, perspective, turn_number, player_id),
                wire,
            )
            self._remember_ledger_turn(game_id, perspective, player_id, turn_number)
        for stale_player_id in stale_player_ids:
            self.bump_player_and_turn_invalidations(
                game_id,
                perspective,
                stale_player_id,
                (turn_number,),
            )
        return bool(wires)

    def _delete_legacy_document(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> None:
        self._delete_if_present(self.document_key(game_id, perspective, turn_number))
        self._legacy_absent.add((game_id, perspective, turn_number))

    def _player_ids_for_turn_replace(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> list[int]:
        player_ids = self._list_player_ids(game_id, perspective, turn_number)
        if player_ids:
            return player_ids
        data = self._read_json_object(self.document_key(game_id, perspective, turn_number))
        if data is None:
            return []
        return self._player_ids_in_document(data)

    def _list_player_ids(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> list[int]:
        prefix = self.document_key(game_id, perspective, turn_number)
        player_ids: list[int] = []
        for segment in self._list_segments(prefix):
            if segment.isdigit():
                player_ids.append(int(segment))
        return sorted(player_ids)

    def _list_segments(self, prefix: str) -> list[str]:
        try:
            return self._storage.list(prefix)
        except NotFoundError, ValidationError:
            return []

    def _read_json_object(self, key: str) -> dict[str, object] | None:
        try:
            data = self._storage.get(key)
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError(f"stored fleet document at {key} must be a JSON object")
        return data

    def _delete_if_present(self, key: str) -> bool:
        try:
            self._storage.delete(key)
        except NotFoundError:
            return False
        return True

    def _remember_ledger_turn(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn_number: int,
    ) -> None:
        with self._generation_lock:
            turns = self._known_ledger_turns.setdefault((game_id, perspective, player_id), set())
            turns.add(turn_number)

    def _forget_ledger_turn(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn_number: int,
    ) -> None:
        with self._generation_lock:
            turns = self._known_ledger_turns.get((game_id, perspective, player_id))
            if turns is not None:
                turns.discard(turn_number)

    def _known_turns_from(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn_number: int,
    ) -> set[int]:
        with self._generation_lock:
            known = self._known_ledger_turns.get((game_id, perspective, player_id), set())
            turns = {stored for stored in known if stored >= turn_number}
        turns.add(turn_number)
        return turns

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
        """Yield stored turn numbers at or after ``turn_number``."""

        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn >= turn_number:
                yield stored_turn

    def _stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        turns_prefix = f"games/{game_id}/{perspective}/turns"
        turn_numbers: list[int] = []
        for segment in self._list_segments(turns_prefix):
            if segment.isdigit():
                turn_numbers.append(int(segment))
        return sorted(turn_numbers)
