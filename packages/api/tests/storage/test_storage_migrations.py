"""Storage-version migration pipeline for breakpoint changes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.serialization import upgrade_legacy_fleet_turn_document
from api.analytics.fleet.storage_migration import (
    fleet_storage_migration,
    migrate_fleet_breakpoint,
)
from api.config import ApiConfig, get_config, set_config
from api.errors import NotFoundError, UnhandledFormatError, ValidationError
from api.storage.boundaries import BREAKPOINT_PATTERNS
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.migrations import (
    CURRENT_STORAGE_VERSION,
    STORAGE_VERSION_KEY,
    MigrationContext,
    StorageMigration,
    generic_rehome,
    open_store,
    version_label,
)
from api.storage_factory import clear_backend_cache, get_storage, production_migrations

_DOCUMENT_STORE_METHODS = (
    "iter_document_paths",
    "has_document",
    "read_document",
    "write_document",
    "remove_document",
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


def _store(backend: FileStorageBackend | MemoryAssetBackend):
    return backend._document_store


def _document_map(backend: MemoryAssetBackend) -> dict:
    store = _store(backend)
    return {path: store.read_document(path) for path in store.iter_document_paths()}


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
            documents=_document_map(backend),
            patterns=_scores_patterns(),
            migrations=(_scores_migration(),),
        )
    assert calls == [1]


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


@pytest.mark.parametrize(
    ("version", "label"),
    [
        (None, "unversioned"),
        (0, "0"),
        (1, "1"),
        (5, "5"),
    ],
)
def test_version_label(version, label):
    assert version_label(version) == label


@pytest.mark.parametrize(
    ("error", "found", "minimum", "maximum", "detail"),
    [
        (
            UnhandledFormatError.below_minimum("0", "1"),
            "0",
            "1",
            None,
            "found version 0, minimum supported version 1",
        ),
        (
            UnhandledFormatError.above_maximum("5", "1"),
            "5",
            None,
            "1",
            "found version 5, maximum supported version 1",
        ),
    ],
)
def test_unhandled_format_error_constructors(error, found, minimum, maximum, detail):
    assert error.http_error == 422
    assert error.found_version == found
    assert error.minimum_version == minimum
    assert error.maximum_version == maximum
    assert str(error) == f"Unhandled storage format: {detail}"


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
        ):
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
        ):
            MemoryAssetBackend(
                documents=seeded,
                minimum_version=None,
                migrations=(),
                current_version=1,
            )
        assert seeded == original


def _storage_source_layer_violations(path: Path) -> list[str]:
    """Return forbidden module names referenced in ``path`` (imports, lazy or not)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_prefixes = ("api.analytics", "api.services", "api.storage_factory")
    hits: list[str] = []

    def _is_forbidden(name: str | None) -> bool:
        if name is None:
            return False
        return any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden_prefixes)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if _is_forbidden(node.module):
                hits.append(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_forbidden(node.value):
                hits.append(node.value)
    for prefix in forbidden_prefixes:
        if prefix in source:
            hits.append(prefix)
    return list(dict.fromkeys(hits))


def test_storage_package_does_not_import_analytics_services_or_factory():
    storage_dir = Path(__file__).resolve().parents[2] / "api" / "storage"
    assert storage_dir.is_dir()
    offenders: list[str] = []
    for path in sorted(storage_dir.rglob("*.py")):
        imported = _storage_source_layer_violations(path)
        if imported:
            relative = path.relative_to(storage_dir)
            offenders.append(f"{relative}: {', '.join(imported)}")
    assert offenders == []


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


def _legacy_players_parent() -> dict:
    return {
        "analyticId": "fleet",
        "gameId": 1,
        "perspective": 1,
        "turn": 3,
        "materializationVersion": FLEET_MATERIALIZATION_VERSION,
        "players": [{"playerId": 8, "playerName": "ace", "records": []}],
    }


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_stale_players_document_with_unparseable_wire_is_deleted_on_open(kind, tmp_path):
    document = {
        "analyticId": "fleet",
        "gameId": 1,
        "perspective": 1,
        "turn": 3,
        "materializationVersion": FLEET_MATERIALIZATION_VERSION - 1,
        "players": [{"playerId": "not-an-int"}],
    }
    with pytest.raises(ValidationError):
        upgrade_legacy_fleet_turn_document(document)
    migrations = (fleet_storage_migration(),)
    if kind == "memory":
        backend = MemoryAssetBackend(documents={FLEET: document}, migrations=migrations)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, migrations=migrations)
    store = _store(backend)
    assert not store.has_document(FLEET)
    fleet_children = [path for path in store.iter_document_paths() if path.startswith(f"{FLEET}/")]
    assert fleet_children == []
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


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
    migrate_fleet_breakpoint(MigrationContext(_store(backend)))
    store = _store(backend)
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == expected
    assert not store.has_document(ledgers_path)
    assert store.read_document(f"{ledgers_path}/8") == LEDGER_WIRE
    assert store.read_document(other_path) == other


def test_open_splits_upgraded_parent_and_retries_as_noop():
    backend = MemoryAssetBackend(
        documents={FLEET: {"ledgers": {"8": LEDGER_WIRE}}},
        migrations=(),
        current_version=0,
    )
    step = fleet_storage_migration()
    store = _store(backend)
    open_store(
        store,
        patterns=BREAKPOINT_PATTERNS,
        migrations=(step,),
        current_version=CURRENT_STORAGE_VERSION,
        minimum_version=None,
    )
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    with pytest.raises(NotFoundError):
        backend.get(FLEET)

    migrate_fleet_breakpoint(MigrationContext(store))
    generic_rehome(store, BREAKPOINT_PATTERNS)
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    assert not store.has_document(FLEET)

    open_store(
        store,
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
    assert not _store(backend).has_document(FLEET)


def test_fleet_document_without_legacy_shape_stays():
    backend = MemoryAssetBackend(
        documents={FLEET: {"note": True}},
        migrations=(fleet_storage_migration(),),
    )
    assert backend.get(FLEET) == {"note": True}


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_document_store_read_returns_a_copy(kind, tmp_path):
    if kind == "memory":
        backend = MemoryAssetBackend(initial={}, migrations=())
    else:
        backend = FileStorageBackend(tmp_path / "data", migrations=())
    store = _store(backend)
    store.write_document("games/1/info", {"name": "keep"})
    loaded = store.read_document("games/1/info")
    assert isinstance(loaded, dict)
    loaded["name"] = "mutated"
    assert store.read_document("games/1/info") == {"name": "keep"}
    assert backend.get("games/1/info") == {"name": "keep"}


@pytest.mark.parametrize("cls", [FileStorageBackend, MemoryAssetBackend])
@pytest.mark.parametrize("name", _DOCUMENT_STORE_METHODS)
def test_backends_do_not_expose_document_store_methods(cls, name):
    assert name not in vars(cls)
