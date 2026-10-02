"""Storage-version migration pipeline for breakpoint changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.serialization import upgrade_legacy_fleet_turn_document
from api.analytics.fleet.storage_migration import (
    fleet_retired_document_holds_path,
    fleet_storage_migration,
    migrate_fleet_breakpoint,
)
from api.config import ApiConfig, get_config, set_config
from api.errors import NotFoundError, UnhandledFormatError
from api.storage import clear_backend_cache, get_storage, production_migrations
from api.storage.boundaries import BREAKPOINT_PATTERNS
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.migrations import (
    CURRENT_STORAGE_VERSION,
    STORAGE_VERSION_KEY,
    MigrationContext,
    StorageMigration,
    _retired_document_location,
    generic_rehome,
    open_store,
)

SCORES = "games/7/1/turns/3/analytics/scores"
SCORES_ROW = f"{SCORES}/inference_rows/4"
SCORES_PLAYER_PATTERN = (
    "games",
    "*",
    "*",
    "turns",
    "*",
    "analytics",
    "scores",
    "inference_rows",
    "*",
)
ROW = {"status": "exact", "playerId": 4}
FLEET = "games/1/1/turns/3/analytics/fleet"
FLEET_PLAYER = f"{FLEET}/8"
LEDGER_WIRE = {
    "ledger": {"playerId": 8, "playerName": "ace", "records": []},
    "provenance": {
        "turnEvidenceAtN": False,
        "priorLedgerAtNMinus1": False,
        "eliminatedAtTurn": False,
    },
    "materializationVersion": FLEET_MATERIALIZATION_VERSION,
    "evidenceGeneration": 0,
}


def _scores_patterns() -> tuple[tuple[str, ...], ...]:
    return BREAKPOINT_PATTERNS + (SCORES_PLAYER_PATTERN,)


def _scores_migration() -> StorageMigration:
    return StorageMigration(
        version=1,
        introduced_pattern=SCORES_PLAYER_PATTERN,
    )


def _open_scores(kind: str, root: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []
    real = generic_rehome

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("api.storage.migrations.generic_rehome", wrapped)
    patterns = _scores_patterns()
    migrations = (_scores_migration(),)
    if kind == "memory":
        backend = MemoryAssetBackend(
            documents={SCORES: {"inference_rows": {"4": ROW}, "kept": True}},
            patterns=patterns,
            migrations=migrations,
        )
    else:
        scores_file = root / f"{SCORES}.json"
        scores_file.parent.mkdir(parents=True)
        scores_file.write_text(
            json.dumps({"inference_rows": {"4": ROW}, "kept": True}),
            encoding="utf-8",
        )
        backend = FileStorageBackend(root, patterns=patterns, migrations=migrations)
    return backend, calls


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_generic_rehome_keeps_logical_get(kind, tmp_path, monkeypatch):
    root = tmp_path / "data"
    backend, calls = _open_scores(kind, root, monkeypatch)
    assert calls == [1]
    assert backend.get(SCORES_ROW) == ROW
    assert backend.get(SCORES) == {"kept": True}
    assert backend.get(STORAGE_VERSION_KEY) == {"version": CURRENT_STORAGE_VERSION}
    with pytest.raises(NotFoundError):
        backend.get(f"{SCORES}/inference_rows/999")

    if kind == "file":
        FileStorageBackend(root, patterns=_scores_patterns(), migrations=(_scores_migration(),))
    else:
        MemoryAssetBackend(
            documents=dict(backend._documents),
            patterns=_scores_patterns(),
            migrations=(_scores_migration(),),
        )
    assert calls == [1]

    parent = backend.get(SCORES)
    assert isinstance(parent, dict)
    parent["inference_rows"] = {"4": dict(ROW)}
    backend.put(SCORES, parent)
    backend.delete(SCORES_ROW)
    with pytest.raises(
        UnhandledFormatError,
        match="found layout from version unversioned, retired by version 1",
    ):
        backend.get(SCORES_ROW)


def test_new_directory_is_stamped_without_migrations(tmp_path, monkeypatch):
    calls: list[str] = []

    def wrapped(context):
        calls.append("fleet")
        return migrate_fleet_breakpoint(context)

    monkeypatch.setattr(
        "api.analytics.fleet.storage_migration.migrate_fleet_breakpoint",
        wrapped,
    )
    root = tmp_path / "data"
    file_backend = FileStorageBackend(root)
    memory_backend = MemoryAssetBackend(initial={})
    assert calls == []
    assert file_backend.get(STORAGE_VERSION_KEY) == {"version": CURRENT_STORAGE_VERSION}
    assert memory_backend.get(STORAGE_VERSION_KEY) == {"version": CURRENT_STORAGE_VERSION}
    FileStorageBackend(root)
    assert calls == []

    bound = (fleet_storage_migration(),)
    FileStorageBackend(tmp_path / "bound", migrations=bound)
    MemoryAssetBackend(initial={}, migrations=bound)
    assert calls == []


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_unversioned_ledgers_document_splits_on_open(kind, tmp_path, monkeypatch):
    calls: list[int] = []

    def wrapped(context):
        calls.append(1)
        return migrate_fleet_breakpoint(context)

    monkeypatch.setattr(
        "api.analytics.fleet.storage_migration.migrate_fleet_breakpoint",
        wrapped,
    )
    document = {"ledgers": {"8": LEDGER_WIRE}}
    migrations = (fleet_storage_migration(),)
    if kind == "memory":
        backend = MemoryAssetBackend(documents={FLEET: document}, migrations=migrations)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, migrations=migrations)
        FileStorageBackend(root, migrations=migrations)
    assert calls == [1]
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


def test_directory_older_than_minimum_is_not_rewritten(tmp_path):
    root = tmp_path / "data"
    info = root / "games" / "1" / "info.json"
    info.parent.mkdir(parents=True)
    payload = b'{"name": "keep"}\n'
    info.write_bytes(payload)
    version = root / "meta" / "storage-version.json"
    version.parent.mkdir(parents=True)
    version_payload = b'{"version": 0}\n'
    version.write_bytes(version_payload)

    with pytest.raises(
        UnhandledFormatError,
        match="found version 0, minimum supported version 1",
    ):
        FileStorageBackend(root, minimum_version=1, migrations=(), current_version=1)

    assert info.read_bytes() == payload
    assert version.read_bytes() == version_payload

    unversioned = tmp_path / "plain"
    plain_info = unversioned / "games" / "1" / "info.json"
    plain_info.parent.mkdir(parents=True)
    plain_info.write_bytes(payload)
    with pytest.raises(
        UnhandledFormatError,
        match="found version unversioned, minimum supported version 1",
    ):
        FileStorageBackend(unversioned, minimum_version=1, migrations=(), current_version=1)
    assert plain_info.read_bytes() == payload
    assert not (unversioned / "meta" / "storage-version.json").exists()

    seeded = {
        "games/1/info": {"name": "keep"},
        STORAGE_VERSION_KEY: {"version": 0},
    }
    original = json.loads(json.dumps(seeded))
    with pytest.raises(
        UnhandledFormatError,
        match="found version 0, minimum supported version 1",
    ):
        MemoryAssetBackend(
            documents=seeded,
            minimum_version=1,
            migrations=(),
            current_version=1,
        )
    assert seeded == original


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_directory_newer_than_current_is_not_rewritten(kind, tmp_path):
    payload = b'{"name": "keep"}\n'
    version_payload = b'{"version": 5}\n'
    if kind == "file":
        root = tmp_path / "data"
        info = root / "games" / "1" / "info.json"
        info.parent.mkdir(parents=True)
        info.write_bytes(payload)
        version = root / "meta" / "storage-version.json"
        version.parent.mkdir(parents=True)
        version.write_bytes(version_payload)
        with pytest.raises(
            UnhandledFormatError,
            match="found version 5, maximum supported version 1",
        ) as raised:
            FileStorageBackend(
                root,
                minimum_version=None,
                migrations=(),
                current_version=1,
            )
        assert info.read_bytes() == payload
        assert version.read_bytes() == version_payload
    else:
        seeded = {
            "games/1/info": {"name": "keep"},
            STORAGE_VERSION_KEY: {"version": 5},
        }
        original = json.loads(json.dumps(seeded))
        with pytest.raises(
            UnhandledFormatError,
            match="found version 5, maximum supported version 1",
        ) as raised:
            MemoryAssetBackend(
                documents=seeded,
                minimum_version=None,
                migrations=(),
                current_version=1,
            )
        assert seeded == original
    message = str(raised.value)
    assert message == "Unhandled storage format: found version 5, maximum supported version 1"
    assert "minimum" not in message
    assert raised.value.http_error == 422
    assert raised.value.found_version == "5"
    assert raised.value.maximum_version == "1"
    assert raised.value.minimum_version is None
    assert raised.value.retired_by_version is None


def test_retired_document_location_is_previous_registry_suffix():
    assert _retired_document_location(
        SCORES_ROW,
        current_breakpoint=SCORES_ROW,
        patterns=_scores_patterns(),
        introduced_pattern=SCORES_PLAYER_PATTERN,
    ) == (SCORES, "inference_rows/4")
    fleet_step = fleet_storage_migration()
    assert _retired_document_location(
        FLEET_PLAYER,
        current_breakpoint=FLEET_PLAYER,
        patterns=BREAKPOINT_PATTERNS,
        introduced_pattern=fleet_step.introduced_pattern,
    ) == (FLEET, "8")
    assert (
        _retired_document_location(
            SCORES,
            current_breakpoint=SCORES,
            patterns=_scores_patterns(),
            introduced_pattern=SCORES_PLAYER_PATTERN,
        )
        is None
    )


def test_production_migrations_bind_fleet_step():
    steps = production_migrations()
    assert len(steps) == 1
    step = steps[0]
    assert step.version == CURRENT_STORAGE_VERSION
    assert step.structural_handler is migrate_fleet_breakpoint
    assert step.holds_retired_path is fleet_retired_document_holds_path


def test_get_storage_file_open_runs_fleet_migration(tmp_path):
    root = tmp_path / "data"
    fleet_file = root / f"{FLEET}.json"
    fleet_file.parent.mkdir(parents=True)
    fleet_file.write_text(json.dumps({"ledgers": {"8": LEDGER_WIRE}}), encoding="utf-8")
    previous = get_config()
    set_config(
        ApiConfig(
            storage_backend="file",
            storage_root=str(root),
            include_dummy_data=False,
        )
    )
    clear_backend_cache()
    try:
        backend = get_storage()
        assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
        with pytest.raises(NotFoundError):
            backend.get(FLEET)
        assert backend.get(STORAGE_VERSION_KEY) == {"version": CURRENT_STORAGE_VERSION}
    finally:
        clear_backend_cache()
        set_config(previous)


def test_unversioned_store_without_steps_fails_closed(tmp_path):
    root = tmp_path / "data"
    info = root / "games" / "1" / "info.json"
    info.parent.mkdir(parents=True)
    payload = b'{"name": "keep"}\n'
    info.write_bytes(payload)
    with pytest.raises(RuntimeError, match="No storage migration registered for version 1"):
        FileStorageBackend(root)
    assert info.read_bytes() == payload
    assert not (root / "meta" / "storage-version.json").exists()

    seeded = {"games/1/info": {"name": "keep"}}
    original = json.loads(json.dumps(seeded))
    with pytest.raises(RuntimeError, match="No storage migration registered for version 1"):
        MemoryAssetBackend(documents=seeded)
    assert seeded == original


def _legacy_players_parent() -> dict:
    return {
        "analyticId": "fleet",
        "gameId": 1,
        "perspective": 1,
        "turn": 3,
        "players": [{"playerId": 8, "playerName": "ace", "records": []}],
    }


@pytest.mark.parametrize("kind", ["memory", "file"])
@pytest.mark.parametrize(
    "document",
    [
        {"ledgers": {"8": LEDGER_WIRE}},
        _legacy_players_parent(),
    ],
)
def test_copied_fleet_document_errors_only_for_held_player(kind, document, tmp_path):
    migrations = (fleet_storage_migration(),)
    if kind == "memory":
        backend = MemoryAssetBackend(initial={}, migrations=migrations)
    else:
        root = tmp_path / "data"
        backend = FileStorageBackend(root, migrations=migrations)
    backend.write_document(FLEET, document)
    with pytest.raises(
        UnhandledFormatError,
        match="found layout from version unversioned, retired by version 1",
    ):
        backend.get(FLEET_PLAYER)
    assert backend.read_document(FLEET) == document
    assert not backend.has_document(FLEET_PLAYER)
    with pytest.raises(NotFoundError):
        backend.get(f"{FLEET}/999")
    assert not backend.has_document(f"{FLEET}/999")
    assert backend.read_document(FLEET) == document


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_unversioned_players_document_splits_on_open(kind, tmp_path):
    document = _legacy_players_parent()
    expected = upgrade_legacy_fleet_turn_document(document)["ledgers"]["8"]
    migrations = (fleet_storage_migration(),)
    if kind == "memory":
        backend = MemoryAssetBackend(documents={FLEET: document}, migrations=migrations)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, migrations=migrations)
    assert backend.get(FLEET_PLAYER) == expected
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


def test_fleet_handler_writes_player_documents_from_players_and_ledgers():
    players = _legacy_players_parent()
    expected = upgrade_legacy_fleet_turn_document(players)["ledgers"]["8"]
    ledgers_path = "games/1/1/turns/4/analytics/fleet"
    ledgers = {"ledgers": {"8": LEDGER_WIRE}, "kept": True}
    other_path = "games/1/1/turns/5/analytics/fleet"
    other = {"note": True}
    backend = MemoryAssetBackend(
        documents={FLEET: players, ledgers_path: ledgers, other_path: other},
        migrations=(),
        current_version=0,
    )
    migrate_fleet_breakpoint(MigrationContext(backend))
    assert not backend.has_document(FLEET)
    assert backend.read_document(FLEET_PLAYER) == expected
    assert not backend.has_document(ledgers_path)
    assert backend.read_document(f"{ledgers_path}/8") == LEDGER_WIRE
    assert backend.read_document(other_path) == other


def test_open_splits_upgraded_parent_and_retries_as_noop():
    backend = MemoryAssetBackend(
        documents={FLEET: {"ledgers": {"8": LEDGER_WIRE}}},
        migrations=(),
        current_version=0,
    )
    step = fleet_storage_migration()
    open_store(
        backend,
        patterns=BREAKPOINT_PATTERNS,
        migrations=(step,),
        current_version=CURRENT_STORAGE_VERSION,
        minimum_version=None,
    )
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    with pytest.raises(NotFoundError):
        backend.get(FLEET)

    migrate_fleet_breakpoint(MigrationContext(backend))
    generic_rehome(backend, BREAKPOINT_PATTERNS)
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    assert not backend.has_document(FLEET)

    open_store(
        backend,
        patterns=BREAKPOINT_PATTERNS,
        migrations=(step,),
        current_version=CURRENT_STORAGE_VERSION,
        minimum_version=None,
    )
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE


def test_empty_ledgers_map_removes_parent():
    backend = MemoryAssetBackend(
        documents={FLEET: {"ledgers": {}}},
        migrations=(fleet_storage_migration(),),
    )
    assert not backend.has_document(FLEET)


def test_fleet_document_without_legacy_shape_stays():
    backend = MemoryAssetBackend(
        documents={FLEET: {"note": True}},
        migrations=(fleet_storage_migration(),),
    )
    assert backend.get(FLEET) == {"note": True}
