"""Storage-version migration pipeline for breakpoint changes."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.storage_migration import (
    FLEET_LEDGERS_KEY,
    fleet_storage_migration,
    migrate_fleet_breakpoint,
    upgrade_legacy_fleet_turn_document,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.analytics.scores.storage_migration import scores_inference_row_storage_migration
from api.config import ApiConfig, get_config, set_config
from api.errors import NotFoundError, UnhandledFormatError, ValidationError
from api.storage.boundaries import BREAKPOINT_PATTERNS, SCORES_INFERENCE_ROW_PATTERN
from api.storage.breakpoint_backend import BreakpointDocumentBackend
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend, MemoryDocumentStore
from api.storage.migrations import (
    DEFAULT_STORAGE_FORMAT,
    STORAGE_VERSION_KEY,
    MigrationContext,
    StorageFormat,
    StorageMigration,
    generic_rehome,
    open_store,
    version_label,
)
from api.storage.path_utils import deep_copy_value
from api.storage_factory import (
    clear_backend_cache,
    get_storage,
    production_migrations,
    production_storage_format,
)
from tests.fleet_fixtures import legacy_fleet_players_document

_BACKEND_METHODS = frozenset({"get", "put", "delete", "list"})

SCORES = "games/7/1/turns/3/analytics/scores"
SCORES_ROW = f"{SCORES}/inference_rows/4"
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


def _storage_format(**overrides) -> StorageFormat:
    return replace(DEFAULT_STORAGE_FORMAT, **overrides)


def _store(backend: BreakpointDocumentBackend):
    return backend._document_store


def _document_map(backend: BreakpointDocumentBackend) -> dict:
    store = _store(backend)
    return {path: store.read_document(path) for path in store.iter_document_paths()}


def _opened_memory(
    documents: dict,
    storage_format: StorageFormat | None = None,
) -> BreakpointDocumentBackend:
    """Open breakpoint documents, then wrap them in the shared backend."""
    resolved = DEFAULT_STORAGE_FORMAT if storage_format is None else storage_format
    store = MemoryDocumentStore({path: deep_copy_value(value) for path, value in documents.items()})
    open_store(store, resolved)
    return BreakpointDocumentBackend(store, resolved)


def _scores_migration() -> StorageMigration:
    """Isolated generic re-home of the scores row breakpoint, as its own version 1."""
    return StorageMigration(
        version=1,
        introduced_pattern=SCORES_INFERENCE_ROW_PATTERN,
    )


def _open_scores(kind: str, root: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []
    real = generic_rehome

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("api.storage.migrations.generic_rehome", wrapped)
    patterns = BREAKPOINT_PATTERNS
    migrations = (_scores_migration(),)
    if kind == "memory":
        backend = _opened_memory(
            {SCORES: {"inference_rows": {"4": ROW}, "kept": True}},
            _storage_format(patterns=patterns, migrations=migrations),
        )
    else:
        scores_file = root / f"{SCORES}.json"
        scores_file.parent.mkdir(parents=True)
        scores_file.write_text(
            json.dumps({"inference_rows": {"4": ROW}, "kept": True}),
            encoding="utf-8",
        )
        backend = FileStorageBackend(
            root,
            storage_format=_storage_format(patterns=patterns, migrations=migrations),
        )
    return backend, calls


def _info_step_format() -> tuple[list[int], StorageFormat]:
    calls: list[int] = []

    def handler(_context: MigrationContext) -> None:
        calls.append(1)

    storage_format = _storage_format(
        migrations=(
            StorageMigration(
                version=1,
                introduced_pattern=("games", "*", "info"),
                structural_handler=handler,
            ),
        ),
    )
    return calls, storage_format


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_generic_rehome_keeps_logical_get(kind, tmp_path, monkeypatch):
    root = tmp_path / "data"
    backend, calls = _open_scores(kind, root, monkeypatch)
    assert calls == [1]
    assert backend.get(SCORES_ROW) == ROW
    assert backend.get(SCORES) == {"kept": True}
    assert backend.get(STORAGE_VERSION_KEY) == {"version": _scores_migration().version}
    with pytest.raises(NotFoundError):
        backend.get(f"{SCORES}/inference_rows/999")

    if kind == "file":
        FileStorageBackend(
            root,
            storage_format=_storage_format(
                patterns=BREAKPOINT_PATTERNS,
                migrations=(_scores_migration(),),
            ),
        )
    else:
        _opened_memory(
            _document_map(backend),
            _storage_format(
                patterns=BREAKPOINT_PATTERNS,
                migrations=(_scores_migration(),),
            ),
        )
    assert calls == [1]


class _CountingStore:
    """Document store that records ``read_document`` paths."""

    def __init__(self, documents: dict) -> None:
        self.documents = documents
        self.reads: list[str] = []

    def iter_document_paths(self):
        yield from tuple(self.documents)

    def has_document(self, breakpoint_path: str) -> bool:
        return breakpoint_path in self.documents

    def read_document(self, breakpoint_path: str):
        self.reads.append(breakpoint_path)
        return self.documents[breakpoint_path]

    def write_document(self, breakpoint_path: str, value) -> None:
        self.documents[breakpoint_path] = value

    def remove_document(self, breakpoint_path: str) -> None:
        del self.documents[breakpoint_path]


class _NoEnumerateStore(_CountingStore):
    """Path enumeration is a failure. Used when open must not walk the tree."""

    def iter_document_paths(self):
        raise AssertionError("open_store enumerated documents")


class _StopAfterFirstUserPath(_CountingStore):
    """Yields one non-stamp path, then fails if the caller keeps walking."""

    def iter_document_paths(self):
        yield next(path for path in self.documents if path != STORAGE_VERSION_KEY)
        raise AssertionError("open_store enumerated past the first user document")


def test_generic_rehome_does_not_read_unrelated_documents():
    turn = "games/7/1/turns/9"
    info = "games/7/info"
    fleet = "games/7/1/turns/3/analytics/fleet"
    documents = {
        turn: {"rst": True},
        info: {"name": "keep"},
        fleet: {"note": True},
        SCORES: {"inference_rows": {"4": ROW}, "kept": True},
        STORAGE_VERSION_KEY: {"version": 0},
    }
    store = _CountingStore(documents)
    generic_rehome(store, BREAKPOINT_PATTERNS, SCORES_INFERENCE_ROW_PATTERN)
    assert store.reads == [SCORES]
    assert documents[SCORES] == {"kept": True}
    assert documents[SCORES_ROW] == ROW
    assert documents[turn] == {"rst": True}
    assert documents[info] == {"name": "keep"}
    assert documents[fleet] == {"note": True}
    assert documents[STORAGE_VERSION_KEY] == {"version": 0}


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
    empty_stamp = {"version": DEFAULT_STORAGE_FORMAT.current_version}
    assert file_backend.get(STORAGE_VERSION_KEY) == empty_stamp
    assert memory_backend.get(STORAGE_VERSION_KEY) == empty_stamp
    assert DEFAULT_STORAGE_FORMAT.current_version == 0
    FileStorageBackend(root)
    assert calls == []

    bound = (fleet_storage_migration(),)
    bound_format = _storage_format(migrations=bound)
    FileStorageBackend(tmp_path / "bound", storage_format=bound_format)
    MemoryAssetBackend(initial={}, storage_format=bound_format)
    assert calls == []


@pytest.mark.parametrize(
    "documents",
    [
        {STORAGE_VERSION_KEY: {"version": DEFAULT_STORAGE_FORMAT.current_version}},
        {
            STORAGE_VERSION_KEY: {"version": DEFAULT_STORAGE_FORMAT.current_version},
            "games/1/info": {"name": "keep"},
        },
    ],
)
def test_stamped_current_store_does_not_enumerate_documents(documents):
    store = _NoEnumerateStore(dict(documents))
    open_store(store, DEFAULT_STORAGE_FORMAT)
    assert store.documents == documents


def test_older_stamp_does_not_enumerate_before_migration():
    info = "games/1/info"
    store = _NoEnumerateStore(
        {
            STORAGE_VERSION_KEY: {"version": 0},
            info: {"name": "keep"},
        }
    )
    calls, storage_format = _info_step_format()
    open_store(store, storage_format)
    assert calls == [1]
    assert store.documents[STORAGE_VERSION_KEY] == {"version": storage_format.current_version}
    assert store.documents[info] == {"name": "keep"}


def test_unstamped_nonempty_store_migrates_without_full_enumeration():
    info = "games/1/info"
    other = "games/2/info"
    store = _StopAfterFirstUserPath(
        {
            info: {"name": "keep"},
            other: {"name": "also"},
        }
    )
    calls, storage_format = _info_step_format()
    open_store(store, storage_format)
    assert calls == [1]
    assert store.documents[STORAGE_VERSION_KEY] == {"version": storage_format.current_version}
    assert store.documents[info] == {"name": "keep"}
    assert store.documents[other] == {"name": "also"}


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
    storage_format = _storage_format(migrations=migrations)
    if kind == "memory":
        backend = _opened_memory({FLEET: document}, storage_format)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, storage_format=storage_format)
        FileStorageBackend(root, storage_format=storage_format)
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


def _info_step(version: int = 1) -> StorageMigration:
    return StorageMigration(version=version, introduced_pattern=("games", "*", "info"))


def test_storage_format_current_version_is_the_highest_step():
    assert DEFAULT_STORAGE_FORMAT.current_version == 0
    assert DEFAULT_STORAGE_FORMAT.minimum_version is None
    one = StorageFormat(patterns=BREAKPOINT_PATTERNS, migrations=(_info_step(),))
    assert one.current_version == 1
    two = StorageFormat(
        patterns=BREAKPOINT_PATTERNS,
        migrations=(_info_step(1), _info_step(2)),
        minimum_version=1,
    )
    assert two.current_version == 2


def test_storage_format_rejects_an_invalid_migration_registry():
    with pytest.raises(RuntimeError, match="versions 1..1 in order; found 1, 1"):
        StorageFormat(
            patterns=BREAKPOINT_PATTERNS,
            migrations=(_info_step(), _info_step()),
        )
    with pytest.raises(RuntimeError, match="versions 1..2 in order; found 2"):
        StorageFormat(
            patterns=BREAKPOINT_PATTERNS,
            migrations=(_info_step(2),),
        )
    with pytest.raises(RuntimeError, match="versions 1..2 in order; found 2, 1"):
        StorageFormat(
            patterns=BREAKPOINT_PATTERNS,
            migrations=(_info_step(2), _info_step(1)),
        )
    with pytest.raises(
        RuntimeError,
        match="Storage migration 1 introduces a breakpoint that is not registered",
    ):
        StorageFormat(
            patterns=BREAKPOINT_PATTERNS,
            migrations=(StorageMigration(version=1, introduced_pattern=("games", "*", "missing")),),
        )
    with pytest.raises(RuntimeError, match="minimum_version 1 exceeds current version 0"):
        StorageFormat(patterns=BREAKPOINT_PATTERNS, migrations=(), minimum_version=1)


_UNREADABLE_STAMP_DETAIL = "storage version stamp is not an object with an integer version"


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
        (
            UnhandledFormatError.unreadable_stamp(),
            "unreadable",
            None,
            None,
            _UNREADABLE_STAMP_DETAIL,
        ),
    ],
)
def test_unhandled_format_error_constructors(error, found, minimum, maximum, detail):
    assert error.http_error == 422
    assert error.found_version == found
    assert error.minimum_version == minimum
    assert error.maximum_version == maximum
    assert str(error) == f"Unhandled storage format: {detail}"


@pytest.mark.parametrize(
    "stamp",
    [
        ["not-an-object"],
        {"version": "1"},
        {"version": True},
    ],
)
def test_unreadable_stamp_is_not_rewritten(stamp, tmp_path):
    info = "games/1/info"
    documents = {
        info: {"name": "keep"},
        STORAGE_VERSION_KEY: stamp,
    }
    expected = json.loads(json.dumps(documents))
    store = _CountingStore(json.loads(json.dumps(documents)))
    with pytest.raises(UnhandledFormatError, match=_UNREADABLE_STAMP_DETAIL) as raised:
        open_store(store, DEFAULT_STORAGE_FORMAT)
    assert str(raised.value) == f"Unhandled storage format: {_UNREADABLE_STAMP_DETAIL}"
    assert raised.value.found_version == "unreadable"
    assert raised.value.http_error == 422
    assert raised.value.minimum_version is None
    assert raised.value.maximum_version is None
    assert store.documents == expected

    root = tmp_path / "data"
    info_file = root / "games" / "1" / "info.json"
    info_file.parent.mkdir(parents=True)
    payload = b'{"name": "keep"}\n'
    info_file.write_bytes(payload)
    version = root / "meta" / "storage-version.json"
    version.parent.mkdir(parents=True)
    version_payload = json.dumps(stamp).encode() + b"\n"
    version.write_bytes(version_payload)
    with pytest.raises(UnhandledFormatError, match=_UNREADABLE_STAMP_DETAIL):
        FileStorageBackend(root)
    assert info_file.read_bytes() == payload
    assert version.read_bytes() == version_payload

    seeded = json.loads(json.dumps(documents))
    original = json.loads(json.dumps(seeded))
    with pytest.raises(UnhandledFormatError, match=_UNREADABLE_STAMP_DETAIL):
        _opened_memory(seeded)
    assert seeded == original


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
        FileStorageBackend(
            root,
            storage_format=_storage_format(migrations=(_info_step(),), minimum_version=1),
        )

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
        FileStorageBackend(
            unversioned,
            storage_format=_storage_format(migrations=(_info_step(),), minimum_version=1),
        )
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
        _opened_memory(
            seeded,
            _storage_format(migrations=(_info_step(),), minimum_version=1),
        )
    assert seeded == original


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_directory_newer_than_current_is_not_rewritten(kind, tmp_path):
    payload = b'{"name": "keep"}\n'
    version_payload = b'{"version": 5}\n'
    storage_format = StorageFormat(
        patterns=BREAKPOINT_PATTERNS,
        migrations=(_info_step(),),
    )
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
            FileStorageBackend(root, storage_format=storage_format)
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
            _opened_memory(seeded, storage_format)
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


def test_production_migrations_bind_fleet_then_scores_rehome():
    storage_format = production_storage_format()
    steps = storage_format.migrations
    assert steps == production_migrations()
    assert len(steps) == 2
    fleet_step, scores_step = steps
    assert fleet_step.version == fleet_storage_migration().version == 1
    assert fleet_step.structural_handler is migrate_fleet_breakpoint
    assert scores_step == scores_inference_row_storage_migration()
    assert scores_step.version == 2
    assert scores_step.structural_handler is None
    assert scores_step.introduced_pattern == SCORES_INFERENCE_ROW_PATTERN
    assert storage_format.current_version == 2


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
        assert backend.get(STORAGE_VERSION_KEY) == {
            "version": production_storage_format().current_version
        }
    finally:
        clear_backend_cache()
        set_config(previous)


def test_production_open_splits_shared_scores_document(tmp_path):
    """A shared scores document becomes one file per player and is removed."""
    root = tmp_path / "data"
    scores_file = root / f"{SCORES}.json"
    scores_file.parent.mkdir(parents=True)
    other = {"status": "exact", "playerId": 5}
    scores_file.write_text(
        json.dumps({"inference_rows": {"4": ROW, "5": other}}),
        encoding="utf-8",
    )
    fleet_file = root / f"{FLEET}.json"
    fleet_file.parent.mkdir(parents=True)
    fleet_file.write_text(json.dumps({"ledgers": {"8": LEDGER_WIRE}}), encoding="utf-8")
    backend = FileStorageBackend(root, storage_format=production_storage_format())
    assert backend.get(SCORES_ROW) == ROW
    assert backend.get(f"{SCORES}/inference_rows/5") == other
    with pytest.raises(NotFoundError):
        backend.get(SCORES)
    assert not scores_file.exists()
    assert (root / f"{SCORES_ROW}.json").is_file()
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    assert backend.get(STORAGE_VERSION_KEY) == {
        "version": production_storage_format().current_version
    }


def test_version_one_directory_splits_scores_without_rerunning_fleet(tmp_path):
    """A directory already at the fleet step only runs the scores re-home."""
    root = tmp_path / "data"
    scores_file = root / f"{SCORES}.json"
    scores_file.parent.mkdir(parents=True)
    scores_file.write_text(json.dumps({"inference_rows": {"4": ROW}}), encoding="utf-8")
    fleet_file = root / f"{FLEET}.json"
    fleet_file.parent.mkdir(parents=True)
    fleet_parent = {"ledgers": {"8": LEDGER_WIRE}, "kept": True}
    fleet_file.write_text(json.dumps(fleet_parent), encoding="utf-8")
    version_file = root / "meta" / "storage-version.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(json.dumps({"version": 1}), encoding="utf-8")
    backend = FileStorageBackend(root, storage_format=production_storage_format())
    assert backend.get(SCORES_ROW) == ROW
    assert not scores_file.exists()
    assert backend.get(FLEET) == fleet_parent
    assert backend.get(STORAGE_VERSION_KEY) == {"version": 2}


def test_default_format_opens_an_unversioned_directory(tmp_path):
    root = tmp_path / "data"
    info = root / "games" / "1" / "info.json"
    info.parent.mkdir(parents=True)
    payload = b'{"name": "keep"}\n'
    info.write_bytes(payload)
    backend = FileStorageBackend(root)
    assert info.read_bytes() == payload
    assert not (root / "meta" / "storage-version.json").exists()
    assert backend.get("games/1/info") == {"name": "keep"}
    FileStorageBackend(root)
    assert info.read_bytes() == payload
    assert not (root / "meta" / "storage-version.json").exists()

    seeded = {"games/1/info": {"name": "keep"}}
    original = json.loads(json.dumps(seeded))
    opened = _opened_memory(seeded)
    assert seeded == original
    assert opened.get("games/1/info") == {"name": "keep"}
    assert not _store(opened).has_document(STORAGE_VERSION_KEY)


def _legacy_players_parent() -> dict:
    return legacy_fleet_players_document(
        FleetTurnSnapshot(
            game_id=1,
            perspective=1,
            turn=3,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
            players=[FleetAcquisitionLedger(player_id=8, player_name="ace")],
        ),
    )


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
    storage_format = _storage_format(migrations=(fleet_storage_migration(),))
    if kind == "memory":
        backend = _opened_memory({FLEET: document}, storage_format)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, storage_format=storage_format)
    store = _store(backend)
    assert not store.has_document(FLEET)
    fleet_children = [path for path in store.iter_document_paths() if path.startswith(f"{FLEET}/")]
    assert fleet_children == []
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_unversioned_players_document_splits_on_open(kind, tmp_path):
    document = _legacy_players_parent()
    expected = upgrade_legacy_fleet_turn_document(document)[FLEET_LEDGERS_KEY]["8"]
    storage_format = _storage_format(migrations=(fleet_storage_migration(),))
    if kind == "memory":
        backend = _opened_memory({FLEET: document}, storage_format)
    else:
        root = tmp_path / "data"
        fleet_file = root / f"{FLEET}.json"
        fleet_file.parent.mkdir(parents=True)
        fleet_file.write_text(json.dumps(document), encoding="utf-8")
        backend = FileStorageBackend(root, storage_format=storage_format)
    assert backend.get(FLEET_PLAYER) == expected
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


def test_fleet_handler_writes_player_documents_from_players_and_ledgers():
    players = _legacy_players_parent()
    expected = upgrade_legacy_fleet_turn_document(players)[FLEET_LEDGERS_KEY]["8"]
    ledgers_path = "games/1/1/turns/4/analytics/fleet"
    ledgers = {"ledgers": {"8": LEDGER_WIRE}, "kept": True}
    other_path = "games/1/1/turns/5/analytics/fleet"
    other = {"note": True}
    backend = _opened_memory(
        {FLEET: players, ledgers_path: ledgers, other_path: other},
        DEFAULT_STORAGE_FORMAT,
    )
    migrate_fleet_breakpoint(MigrationContext(_store(backend)))
    store = _store(backend)
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == expected
    assert not store.has_document(ledgers_path)
    assert store.read_document(f"{ledgers_path}/8") == LEDGER_WIRE
    assert store.read_document(other_path) == other


def test_open_splits_upgraded_parent_and_retries_as_noop():
    backend = _opened_memory(
        {FLEET: {"ledgers": {"8": LEDGER_WIRE}}},
        DEFAULT_STORAGE_FORMAT,
    )
    step = fleet_storage_migration()
    store = _store(backend)
    opened = StorageFormat(
        patterns=BREAKPOINT_PATTERNS,
        migrations=(step,),
    )
    open_store(store, opened)
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    with pytest.raises(NotFoundError):
        backend.get(FLEET)

    migrate_fleet_breakpoint(MigrationContext(store))
    generic_rehome(store, BREAKPOINT_PATTERNS, fleet_storage_migration().introduced_pattern)
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE
    assert not store.has_document(FLEET)

    open_store(store, opened)
    assert backend.get(FLEET_PLAYER) == LEDGER_WIRE


def test_interrupted_fleet_handler_converges_on_rerun():
    other = {"ledger": {"playerId": 9}}
    backend = _opened_memory(
        {FLEET: {"ledgers": {"8": LEDGER_WIRE, "9": other}}},
        DEFAULT_STORAGE_FORMAT,
    )
    store = _store(backend)
    store.write_document(FLEET_PLAYER, LEDGER_WIRE)
    assert store.has_document(FLEET)
    assert not store.has_document(f"{FLEET}/9")
    assert not store.has_document(STORAGE_VERSION_KEY)

    migrate_fleet_breakpoint(MigrationContext(store))
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == LEDGER_WIRE
    assert store.read_document(f"{FLEET}/9") == other
    assert not store.has_document(STORAGE_VERSION_KEY)

    migrate_fleet_breakpoint(MigrationContext(store))
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == LEDGER_WIRE
    assert store.read_document(f"{FLEET}/9") == other

    opened = _storage_format(migrations=(fleet_storage_migration(),))
    open_store(store, opened)
    assert store.read_document(STORAGE_VERSION_KEY) == {"version": opened.current_version}
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == LEDGER_WIRE
    assert store.read_document(f"{FLEET}/9") == other


def test_fleet_handler_skips_non_player_ledger_entries():
    document = {
        "ledgers": {
            "8": LEDGER_WIRE,
            "note": {"ledger": {}},
            "9": "not-a-ledger",
            "10": None,
        }
    }
    backend = _opened_memory(
        {FLEET: document},
        DEFAULT_STORAGE_FORMAT,
    )
    migrate_fleet_breakpoint(MigrationContext(_store(backend)))
    store = _store(backend)
    assert not store.has_document(FLEET)
    assert store.read_document(FLEET_PLAYER) == LEDGER_WIRE
    for skipped in ("note", "9", "10"):
        assert not store.has_document(f"{FLEET}/{skipped}")


def test_empty_ledgers_map_removes_parent():
    backend = _opened_memory(
        {FLEET: {"ledgers": {}}},
        _storage_format(migrations=(fleet_storage_migration(),)),
    )
    assert not _store(backend).has_document(FLEET)


def test_fleet_document_without_legacy_shape_stays():
    backend = _opened_memory(
        {FLEET: {"note": True}},
        _storage_format(migrations=(fleet_storage_migration(),)),
    )
    assert backend.get(FLEET) == {"note": True}


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_document_store_read_returns_a_copy(kind, tmp_path):
    if kind == "memory":
        backend = MemoryAssetBackend(initial={})
    else:
        backend = FileStorageBackend(tmp_path / "data")
    store = _store(backend)
    store.write_document("games/1/info", {"name": "keep"})
    loaded = store.read_document("games/1/info")
    assert isinstance(loaded, dict)
    loaded["name"] = "mutated"
    assert store.read_document("games/1/info") == {"name": "keep"}
    assert backend.get("games/1/info") == {"name": "keep"}


def _public_methods(cls: type) -> set[str]:
    names: set[str] = set()
    for klass in cls.__mro__:
        if klass is object:
            break
        for name, value in vars(klass).items():
            if name.startswith("_") or not callable(value):
                continue
            names.add(name)
    return names


@pytest.mark.parametrize("cls", [FileStorageBackend, MemoryAssetBackend])
def test_public_backend_surface_is_shared_crud(cls):
    assert _public_methods(cls) == _BACKEND_METHODS
    for name in _BACKEND_METHODS:
        assert getattr(cls, name) is getattr(BreakpointDocumentBackend, name)
