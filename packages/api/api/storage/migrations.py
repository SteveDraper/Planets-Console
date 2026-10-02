"""Versioned breakpoint migrations for one data directory.

The directory carries one storage version at ``meta/storage-version``. An empty
directory is stamped with the current version and does not run migrations.
Older supported directories run the remaining steps in order, then stamp the
current version. A directory older than the minimum still supported raises
``UnhandledFormatError`` and is left unchanged.

A structural handler is registered by the analytic that owns the document
shape. Generic re-home splits each stored document onto longer breakpoints in
the current registry when the logical key is unchanged. Handlers see JSON
documents and keys.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from api.errors import NotFoundError, UnhandledFormatError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BreakpointPatterns,
    pattern_matches_breakpoint,
    resolve_breakpoint,
)
from api.storage.documents import partition_breakpoint_document
from api.storage.path_utils import deep_copy_value, resolve_path

STORAGE_VERSION_KEY = "meta/storage-version"
CURRENT_STORAGE_VERSION = 1
# None means an unversioned directory is still supported.
MINIMUM_STORAGE_VERSION: int | None = None

_UNREADABLE_VERSION = "unreadable"


class DocumentStore(Protocol):
    """Raw breakpoint documents. Callers do not resolve logical suffixes."""

    def iter_document_paths(self) -> Iterator[str]: ...

    def has_document(self, breakpoint_path: str) -> bool: ...

    def read_document(self, breakpoint_path: str) -> JSONValue: ...

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None: ...

    def remove_document(self, breakpoint_path: str) -> None: ...


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
            yield path, deep_copy_value(self._store.read_document(path))

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
    documents it owns. When there is no handler, generic re-home splits each
    document onto the current registry. ``holds_retired_path``, when set,
    reports whether a copied-in parent still contains the retired suffix when
    that suffix is not a JSON path in the parent. Re-home residue is
    ``resolve_path`` of the suffix the previous registry stored.
    """

    version: int
    introduced_pattern: tuple[str, ...]
    structural_handler: StructuralHandler | None = None
    holds_retired_path: Callable[[JSONValue, str], bool] | None = None


def version_label(version: int | None) -> str:
    """Return the label used in ``UnhandledFormatError``."""
    if version is None:
        return "unversioned"
    return str(version)


def open_store(
    store: DocumentStore,
    *,
    patterns: BreakpointPatterns,
    migrations: tuple[StorageMigration, ...],
    current_version: int,
    minimum_version: int | None,
) -> None:
    """Stamp ``store`` at ``current_version``, running any migrations still due."""
    _reject_duplicate_versions(migrations, current_version)
    user_paths = [path for path in store.iter_document_paths() if path != STORAGE_VERSION_KEY]
    has_version = store.has_document(STORAGE_VERSION_KEY)
    if not user_paths and not has_version:
        _stamp(store, current_version)
        return

    found = _read_version(store, minimum_version) if has_version else None
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

    by_version = {step.version: step for step in migrations}
    context = MigrationContext(store)
    for version in range(stored + 1, current_version + 1):
        step = by_version.get(version)
        if step is None:
            raise RuntimeError(f"No storage migration registered for version {version}")
        _run_step(step, context, store, patterns)
    _stamp(store, current_version)


def generic_rehome(store: DocumentStore, patterns: BreakpointPatterns) -> None:
    """Split each stored document onto longer breakpoints in ``patterns``.

    Newly separate breakpoint documents are written. The parent is rewritten
    without those keys, or deleted when it is empty.
    """
    paths = [path for path in store.iter_document_paths() if path != STORAGE_VERSION_KEY]
    for path in paths:
        if not store.has_document(path):
            continue
        document = deep_copy_value(store.read_document(path))
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


def superseded_layout_error(
    store: DocumentStore,
    path: str,
    *,
    patterns: BreakpointPatterns,
    migrations: tuple[StorageMigration, ...],
) -> UnhandledFormatError | None:
    """Return an error when ``path`` exists only on a breakpoint this version retired.

    Called after the current breakpoint document is missing. A hit on the current
    document does not consult the retired breakpoint. The previous location is
    ``resolve_breakpoint`` on the registry without the introduced pattern -- the
    same pairing generic re-home inverts when it partitions onto the current
    registry. Residue is ``resolve_path`` of that suffix.
    """
    try:
        breakpoint_path, _suffix = resolve_breakpoint(path, patterns)
    except ValidationError:
        return None
    for step in migrations:
        if not pattern_matches_breakpoint(step.introduced_pattern, breakpoint_path):
            continue
        location = _retired_document_location(
            path,
            current_breakpoint=breakpoint_path,
            patterns=patterns,
            introduced_pattern=step.introduced_pattern,
        )
        if location is None:
            continue
        old_breakpoint, old_suffix = location
        if not store.has_document(old_breakpoint):
            continue
        document = store.read_document(old_breakpoint)
        if _document_holds_suffix(document, old_suffix):
            return _retired_layout_error(step)
        holds_path = step.holds_retired_path
        if holds_path is not None and holds_path(document, old_suffix):
            return _retired_layout_error(step)
    return None


def _retired_document_location(
    path: str,
    *,
    current_breakpoint: str,
    patterns: BreakpointPatterns,
    introduced_pattern: tuple[str, ...],
) -> tuple[str, str] | None:
    """Return where ``path`` lived before ``introduced_pattern`` existed.

    ``(old_breakpoint, old_suffix)`` is the previous-registry result from
    ``resolve_breakpoint``. ``None`` means this pattern did not shorten the
    document that stores ``path``.
    """
    reduced = tuple(pattern for pattern in patterns if pattern != introduced_pattern)
    try:
        old_breakpoint, old_suffix = resolve_breakpoint(path, reduced)
    except ValidationError:
        return None
    if old_breakpoint == current_breakpoint or old_suffix is None:
        return None
    return old_breakpoint, old_suffix


def _document_holds_suffix(document: JSONValue, suffix: str) -> bool:
    try:
        resolve_path(document, suffix)
    except NotFoundError, ValidationError:
        return False
    return True


def _retired_layout_error(step: StorageMigration) -> UnhandledFormatError:
    previous = step.version - 1
    return UnhandledFormatError.retired_layout(
        version_label(previous if previous >= 1 else None),
        version_label(step.version),
    )


def _run_step(
    step: StorageMigration,
    context: MigrationContext,
    store: DocumentStore,
    patterns: BreakpointPatterns,
) -> None:
    if step.introduced_pattern not in patterns:
        raise RuntimeError(
            f"Storage migration {step.version} introduces a breakpoint that is not registered"
        )
    if step.structural_handler is not None:
        step.structural_handler(context)
    else:
        generic_rehome(store, patterns)


def _reject_duplicate_versions(
    migrations: tuple[StorageMigration, ...],
    current_version: int,
) -> None:
    seen: set[int] = set()
    for step in migrations:
        if step.version < 1 or step.version > current_version:
            raise RuntimeError(
                f"Storage migration version {step.version} is outside 1..{current_version}"
            )
        if step.version in seen:
            raise RuntimeError(f"Duplicate storage migration version {step.version}")
        seen.add(step.version)


def _is_below_minimum(found: int | None, minimum: int | None) -> bool:
    if minimum is None:
        return False
    if found is None:
        return True
    return found < minimum


def _read_version(store: DocumentStore, minimum_version: int | None) -> int:
    payload = store.read_document(STORAGE_VERSION_KEY)
    minimum = version_label(minimum_version)
    if not isinstance(payload, dict):
        raise UnhandledFormatError.below_minimum(_UNREADABLE_VERSION, minimum)
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnhandledFormatError.below_minimum(_UNREADABLE_VERSION, minimum)
    return version


def _stamp(store: DocumentStore, version: int) -> None:
    store.write_document(STORAGE_VERSION_KEY, {"version": version})
