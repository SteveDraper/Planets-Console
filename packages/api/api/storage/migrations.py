"""Versioned breakpoint migrations for one data directory.

The directory carries one storage version at ``meta/storage-version``. An empty
directory is stamped with the current version and does not run migrations.
Older supported directories run the remaining steps in order, then stamp the
current version. A directory older than the minimum still supported, newer
than the current version, or carrying a stamp that is not an object with an
integer version, raises ``UnhandledFormatError`` and is left unchanged.
Documents written outside the app after the stamp are unsupported; this module
does not detect them.

A structural handler is registered by the analytic that owns the document
shape. Generic re-home splits documents that held the introduced breakpoint's
keys as an in-document suffix. Handlers see JSON documents and keys.

Steps are not atomic across documents. The version stamp is written only after
every due step finishes. Every step must be safe to re-run: it writes new
documents before removing or shrinking the old one, so a directory left
unstamped mid-step converges on the next open.

``StorageFormat`` is the registry a backend opens with. Its current version
is the highest registered step, or 0 when it registers none. Steps must be
versions ``1..N`` in order. ``minimum_version`` of ``None`` means an
unversioned directory is still supported.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from api.errors import UnhandledFormatError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BREAKPOINT_PATTERNS,
    BreakpointPatterns,
    is_rehome_candidate,
    pattern_matches_breakpoint,
    rehome_source_patterns,
)
from api.storage.document_store import DocumentStore
from api.storage.documents import partition_breakpoint_document

STORAGE_VERSION_KEY = "meta/storage-version"


class MigrationContext:
    """JSON documents and breakpoint paths visible to a structural handler."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def iter_documents(self, pattern: tuple[str, ...]) -> Iterator[tuple[str, JSONValue]]:
        """Yield ``(breakpoint_path, document)`` for paths that match ``pattern``."""
        matches = [
            path
            for path in self._store.iter_document_paths()
            if pattern_matches_breakpoint(pattern, path)
        ]
        for path in matches:
            if not self._store.has_document(path):
                continue
            yield path, self._store.read_document(path)

    def put_document(self, breakpoint_path: str, value: JSONValue) -> None:
        self._store.write_document(breakpoint_path, value)

    def delete_document(self, breakpoint_path: str) -> None:
        self._store.remove_document(breakpoint_path)


StructuralHandler = Callable[[MigrationContext], None]


@dataclass(frozen=True)
class StorageMigration:
    """One step that brings a directory to ``version``.

    ``introduced_pattern`` is the longer breakpoint this step adds. A structural
    handler rewrites document shape, including writing any new breakpoint
    documents it owns. When there is no handler, generic re-home splits
    documents at the longest registered prefix of that pattern.
    """

    version: int
    introduced_pattern: tuple[str, ...]
    structural_handler: StructuralHandler | None = None


def _highest_step_version(migrations: tuple[StorageMigration, ...]) -> int:
    """Return the highest step version, or 0 when ``migrations`` is empty."""
    if not migrations:
        return 0
    return max(step.version for step in migrations)


def _validate_storage_format(
    migrations: tuple[StorageMigration, ...],
    patterns: BreakpointPatterns,
    minimum_version: int | None,
) -> None:
    """Raise when steps are not versions ``1..N`` or ``minimum_version`` is too high.

    ``N`` is the highest step version. An empty tuple is current version 0.
    Each step must introduce a registered breakpoint. ``minimum_version`` of
    ``None`` is allowed. A numeric minimum must not exceed the current
    version. This is an internal registry bug, not a property of stored data.
    """
    versions = [step.version for step in migrations]
    current_version = _highest_step_version(migrations)
    if versions != list(range(1, current_version + 1)):
        found = ", ".join(str(version) for version in versions)
        raise RuntimeError(
            f"Storage migrations must be versions 1..{current_version} in order; found {found}"
        )
    for step in migrations:
        if step.introduced_pattern not in patterns:
            raise RuntimeError(
                f"Storage migration {step.version} introduces a breakpoint that is not registered"
            )
    if minimum_version is not None and minimum_version > current_version:
        raise RuntimeError(
            f"minimum_version {minimum_version} exceeds current version {current_version}"
        )


@dataclass(frozen=True)
class StorageFormat:
    """Breakpoint registry for one data directory.

    ``current_version`` is the highest registered step, or 0 when ``migrations``
    is empty. ``minimum_version`` of ``None`` means an unversioned directory is
    still supported. Bind analytic steps with ``replace`` on
    ``DEFAULT_STORAGE_FORMAT``.
    """

    patterns: BreakpointPatterns
    migrations: tuple[StorageMigration, ...] = ()
    minimum_version: int | None = None

    def __post_init__(self) -> None:
        _validate_storage_format(self.migrations, self.patterns, self.minimum_version)

    @property
    def current_version(self) -> int:
        """Highest registered step version, or 0 when no steps are registered."""
        return _highest_step_version(self.migrations)


# Patterns for this build, with no steps. Current version is 0: an empty
# directory is stamped 0, and an unversioned directory is already current.
# ``minimum_version`` of None means an unversioned directory is still supported.
DEFAULT_STORAGE_FORMAT = StorageFormat(
    patterns=BREAKPOINT_PATTERNS,
    migrations=(),
    minimum_version=None,
)


def version_label(version: int | None) -> str:
    """Return the label used in ``UnhandledFormatError``."""
    if version is None:
        return "unversioned"
    return str(version)


def open_store(store: DocumentStore, storage_format: StorageFormat) -> None:
    """Stamp ``store`` at ``storage_format.current_version``, running migrations still due."""
    current_version = storage_format.current_version
    minimum_version = storage_format.minimum_version
    has_version = store.has_document(STORAGE_VERSION_KEY)
    if not has_version and not _has_user_document(store):
        stamp_version(store, current_version)
        return

    found = _read_version(store) if has_version else None
    if _is_below_minimum(found, minimum_version):
        raise UnhandledFormatError.below_minimum(
            version_label(found),
            version_label(minimum_version),
        )
    if found is not None and found > current_version:
        raise UnhandledFormatError.above_maximum(
            version_label(found),
            version_label(current_version),
        )
    stored = 0 if found is None else found
    if stored == current_version:
        return

    by_version = {step.version: step for step in storage_format.migrations}
    context = MigrationContext(store)
    for version in range(stored + 1, current_version + 1):
        step = by_version.get(version)
        if step is None:
            raise RuntimeError(f"No storage migration registered for version {version}")
        _run_step(step, context, store, storage_format.patterns)
    stamp_version(store, current_version)


def generic_rehome(
    store: DocumentStore,
    patterns: BreakpointPatterns,
    introduced_pattern: tuple[str, ...],
) -> None:
    """Split documents that hold ``introduced_pattern`` onto that breakpoint.

    Only the longest registered prefix of ``introduced_pattern`` is read.
    Newly separate breakpoint documents are written. The parent is rewritten
    without those keys, or deleted when it is empty.
    """
    source_patterns = rehome_source_patterns(introduced_pattern, patterns)
    paths = [
        path
        for path in store.iter_document_paths()
        if path != STORAGE_VERSION_KEY
        and is_rehome_candidate(path, introduced_pattern, source_patterns)
    ]
    for path in paths:
        if not store.has_document(path):
            continue
        document = store.read_document(path)
        partitioned = partition_breakpoint_document(path, document, patterns)
        if partitioned.get(path) == document and set(partitioned) == {path}:
            continue
        for dest, value in partitioned.items():
            if dest == path:
                continue
            store.write_document(dest, value)
        remaining = partitioned.get(path)
        if remaining == {}:
            store.remove_document(path)
        elif remaining is not None:
            store.write_document(path, remaining)


def _run_step(
    step: StorageMigration,
    context: MigrationContext,
    store: DocumentStore,
    patterns: BreakpointPatterns,
) -> None:
    if step.structural_handler is not None:
        step.structural_handler(context)
    else:
        generic_rehome(store, patterns, step.introduced_pattern)


def _has_user_document(store: DocumentStore) -> bool:
    return any(path != STORAGE_VERSION_KEY for path in store.iter_document_paths())


def _is_below_minimum(found: int | None, minimum: int | None) -> bool:
    if minimum is None:
        return False
    if found is None:
        return True
    return found < minimum


def _read_version(store: DocumentStore) -> int:
    payload = store.read_document(STORAGE_VERSION_KEY)
    version = payload.get("version") if isinstance(payload, dict) else None
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnhandledFormatError.unreadable_stamp()
    return version


def stamp_version(store: DocumentStore, version: int) -> None:
    """Write the storage version document. Does not run migrations."""
    store.write_document(STORAGE_VERSION_KEY, {"version": version})
