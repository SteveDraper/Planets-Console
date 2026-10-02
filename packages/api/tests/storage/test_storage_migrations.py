"""Storage-version migration pipeline for breakpoint changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.storage_migration import (
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
    StorageMigration,
    generic_rehome,
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
        rehome_map_suffix="inference_rows",
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
    with pytest.raises(UnhandledFormatError, match="found version unversioned"):
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
def test_fleet_handler_splits_ledgers_document(kind, tmp_path, monkeypatch):
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

    with pytest.raises(UnhandledFormatError, match="found version 0"):
        FileStorageBackend(root, minimum_version=1, migrations=(), current_version=1)

    assert info.read_bytes() == payload
    assert version.read_bytes() == version_payload

    unversioned = tmp_path / "plain"
    plain_info = unversioned / "games" / "1" / "info.json"
    plain_info.parent.mkdir(parents=True)
    plain_info.write_bytes(payload)
    with pytest.raises(UnhandledFormatError, match="found version unversioned"):
        FileStorageBackend(unversioned, minimum_version=1, migrations=(), current_version=1)
    assert plain_info.read_bytes() == payload
    assert not (unversioned / "meta" / "storage-version.json").exists()

    seeded = {
        "games/1/info": {"name": "keep"},
        STORAGE_VERSION_KEY: {"version": 0},
    }
    original = json.loads(json.dumps(seeded))
    with pytest.raises(UnhandledFormatError, match="found version 0"):
        MemoryAssetBackend(
            documents=seeded,
            minimum_version=1,
            migrations=(),
            current_version=1,
        )
    assert seeded == original


def test_production_migrations_bind_fleet_step():
    steps = production_migrations()
    assert len(steps) == 1
    step = steps[0]
    assert step.version == CURRENT_STORAGE_VERSION
    assert step.structural_handler is migrate_fleet_breakpoint


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


def test_copied_fleet_document_is_unhandled(tmp_path):
    root = tmp_path / "data"
    backend = FileStorageBackend(root, migrations=(fleet_storage_migration(),))
    fleet_file = root / f"{FLEET}.json"
    fleet_file.parent.mkdir(parents=True)
    fleet_file.write_text(json.dumps({"ledgers": {"8": LEDGER_WIRE}}), encoding="utf-8")
    with pytest.raises(UnhandledFormatError, match="minimum supported version 1"):
        backend.get(FLEET_PLAYER)
    assert fleet_file.is_file()
    assert not (root / f"{FLEET_PLAYER}.json").exists()
