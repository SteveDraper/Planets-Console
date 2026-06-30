"""Read, write, and invalidate fleet turn snapshots."""

from __future__ import annotations

import threading
from collections.abc import Callable

from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    FLEET_LEDGERS_KEY,
    FLEET_MATERIALIZATION_VERSION,
)
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


class FleetSnapshotPersistenceService:
    """Persist fleet acquisition ledgers at turn-scoped analytic breakpoints.

    Logical document path:
    ``games/{gameId}/{perspective}/turns/{turn}/analytics/fleet``

    In-document keys: ``ledgers/{playerId}`` -- each entry is one
    **fleet acquisition ledger** plus **fleet materialization provenance** and
    ``materializationVersion``.

    Scores-invalidation coupling (F2.x): when scores inference rows are cleared
    for host turn *H*, fleet snapshots at turns ``>= H`` for the same perspective
    must be re-materialized so build evidence and reconciliation stay aligned.
    ``InferenceInvalidationService.on_inference_evidence_updated`` performs that
    invalidation when inference rows are persisted or held solutions stream in.
    Fleet turn-document invalidation (``invalidate_for_turn_write``) is independent
    of scores pair-aware invalidation (turn *T* and *T-1*); both hooks run from
    ``on_turn_stored`` today.

    **Invalidation generation:** Each ``(game_id, perspective)`` pair has a
    monotonic counter bumped on every ``invalidate_for_turn_write`` call. Gap-fill
    in ``get_or_materialize_fleet_snapshot`` records the generation at chain start
    and aborts (then retries from a fresh anchor) when the counter advances during
    multi-turn materialization. Invalidation does not block on gap-fill; concurrent
    invalidation callbacks only bump the counter and delete stored snapshots.

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
    ) -> None:
        self._storage = storage
        self._on_snapshot_persisted = on_snapshot_persisted
        self._invalidation_generation: dict[tuple[int, int], int] = {}
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
            self._bump_invalidation_generation(game_id, perspective)
            return None
        return persisted

    def put_ledger(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted: PersistedFleetLedger,
    ) -> None:
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
        document = self._load_or_create_document(game_id, perspective, turn_number)
        ledgers = self._ledgers_object(document)
        ledgers[str(player_id)] = persisted_fleet_ledger_to_json(to_store)
        self._write_document(game_id, perspective, turn_number, document)
        if self._on_snapshot_persisted is not None:
            self._on_snapshot_persisted(game_id, perspective, turn_number)

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
        if self._on_snapshot_persisted is not None:
            self._on_snapshot_persisted(game_id, perspective, turn_number)

    @property
    def on_snapshot_persisted(self) -> OnSnapshotPersistedCallback | None:
        return self._on_snapshot_persisted

    @on_snapshot_persisted.setter
    def on_snapshot_persisted(self, callback: OnSnapshotPersistedCallback | None) -> None:
        self._on_snapshot_persisted = callback

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

    def invalidation_generation(self, game_id: int, perspective: int) -> int:
        """Return the current invalidation generation for one perspective scope."""
        with self._generation_lock:
            return self._invalidation_generation.get((game_id, perspective), 0)

    def invalidate_for_turn_write(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> set[int]:
        """Drop fleet snapshots at turns >= turn_number for one perspective."""
        cleared: set[int] = set()
        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn < turn_number:
                continue
            if not self._document_exists(game_id, perspective, stored_turn):
                continue
            self.delete_snapshot(game_id, perspective, stored_turn)
            cleared.add(stored_turn)
        self._bump_invalidation_generation(game_id, perspective)
        return cleared

    def _bump_invalidation_generation(self, game_id: int, perspective: int) -> None:
        with self._generation_lock:
            key = (game_id, perspective)
            self._invalidation_generation[key] = self._invalidation_generation.get(key, 0) + 1

    def _document_exists(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> bool:
        try:
            data = self._storage.get(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            return False
        return data is not None

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
                self.delete_snapshot(game_id, perspective, turn_number)
                self._bump_invalidation_generation(game_id, perspective)
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
        self._bump_invalidation_generation(game_id, perspective)
        return False

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
