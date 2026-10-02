"""Versioned breakpoint migrations for one data directory.

The directory carries one storage version at ``meta/storage-version``. An empty
directory is stamped with the current version and does not run migrations.
Older supported directories run the remaining steps in order, then stamp the
current version. A directory older than the minimum still supported raises
``UnhandledFormatError`` and is left unchanged.

A structural handler is registered by the analytic that owns the document
shape. Generic re-home moves a nested map onto a longer breakpoint when the
logical key is unchanged. Handlers see JSON documents and keys.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from api.errors import UnhandledFormatError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BreakpointPatterns,
    pattern_matches_breakpoint,
    resolve_breakpoint,
)
from api.storage.path_utils import deep_copy_value

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
    handler rewrites document shape before generic re-home. ``rehome_map_suffix``
    is the in-document map whose keys become the new path segment.
    ``retires_parent`` means a leftover parent document is the old layout when it
    still contains one of ``retired_keys``. A parent without those keys is a
    current document at the shorter breakpoint.
    """

    version: int
    introduced_pattern: tuple[str, ...]
    structural_handler: StructuralHandler | None = None
    rehome_map_suffix: str | None = None
    retires_parent: bool = False
    retired_keys: tuple[str, ...] = ()


def version_label(version: int | None) -> str:
    """Return the label used in ``UnhandledFormatError``."""
    if version is None:
        return "unversioned"
    return str(version)


def production_migrations() -> tuple[StorageMigration, ...]:
    """Return the migrations bound into every store open.

    Fleet owns the players/ledgers shape rewrite. Storage calls it here so a
    backend runs the handler on open without the analytic probing the old key.
    """
    from api.analytics.fleet.storage_migration import fleet_storage_migration

    return (fleet_storage_migration(),)


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
        raise UnhandledFormatError(version_label(found), version_label(minimum_version))
    if found is not None and found > current_version:
        raise UnhandledFormatError(version_label(found), version_label(minimum_version))
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


def generic_rehome(
    store: DocumentStore,
    introduced_pattern: tuple[str, ...],
    map_suffix: str,
    patterns: BreakpointPatterns,
) -> None:
    """Move each child of ``map_suffix`` onto ``introduced_pattern``.

    The logical key ``{parent}/{map_suffix}/{child}`` keeps the same JSON value.
    Those children are removed from the parent document.
    """
    reduced = tuple(pattern for pattern in patterns if pattern != introduced_pattern)
    paths = [path for path in store.iter_document_paths() if path != STORAGE_VERSION_KEY]
    for path in paths:
        probe = f"{path}/{map_suffix}/_"
        try:
            new_breakpoint, new_suffix = resolve_breakpoint(probe, patterns)
            old_breakpoint, _old_suffix = resolve_breakpoint(probe, reduced)
        except ValidationError:
            continue
        if new_breakpoint != probe or new_suffix is not None:
            continue
        if old_breakpoint != path:
            continue
        if not pattern_matches_breakpoint(introduced_pattern, new_breakpoint):
            continue
        if not store.has_document(path):
            continue
        document = deep_copy_value(store.read_document(path))
        if not isinstance(document, dict):
            continue
        mapping = _mapping_at(document, map_suffix)
        if mapping is None:
            continue
        for child_key, child_value in mapping.items():
            if not _is_path_segment(child_key):
                continue
            store.write_document(
                f"{path}/{map_suffix}/{child_key}",
                deep_copy_value(child_value),
            )
        _delete_mapping(document, map_suffix)
        store.write_document(path, document)


def superseded_layout_error(
    store: DocumentStore,
    path: str,
    *,
    patterns: BreakpointPatterns,
    migrations: tuple[StorageMigration, ...],
) -> UnhandledFormatError | None:
    """Return an error when ``path`` exists only on a breakpoint this version retired.

    Called after the current breakpoint document is missing. A hit on the current
    document does not consult the retired breakpoint.
    """
    try:
        breakpoint_path, _suffix = resolve_breakpoint(path, patterns)
    except ValidationError:
        return None
    for step in migrations:
        if not pattern_matches_breakpoint(step.introduced_pattern, breakpoint_path):
            continue
        reduced = tuple(pattern for pattern in patterns if pattern != step.introduced_pattern)
        try:
            old_breakpoint, old_suffix = resolve_breakpoint(path, reduced)
        except ValidationError:
            continue
        if old_breakpoint == breakpoint_path or not store.has_document(old_breakpoint):
            continue
        if step.retires_parent:
            if _parent_holds_retired_keys(store, old_breakpoint, step.retired_keys):
                previous = step.version - 1
                found = "unversioned" if previous < 1 else str(previous)
                return UnhandledFormatError(found, str(step.version))
            continue
        if _rehome_child_still_present(
            store,
            old_breakpoint,
            old_suffix,
            step.rehome_map_suffix,
        ):
            previous = step.version - 1
            found = "unversioned" if previous < 1 else str(previous)
            return UnhandledFormatError(found, str(step.version))
    return None


def _parent_holds_retired_keys(
    store: DocumentStore,
    old_breakpoint: str,
    retired_keys: tuple[str, ...],
) -> bool:
    if not retired_keys:
        return True
    document = store.read_document(old_breakpoint)
    return isinstance(document, dict) and any(key in document for key in retired_keys)


def _rehome_child_still_present(
    store: DocumentStore,
    old_breakpoint: str,
    old_suffix: str | None,
    map_suffix: str | None,
) -> bool:
    if map_suffix is None or old_suffix is None:
        return False
    prefix = f"{map_suffix}/"
    if not old_suffix.startswith(prefix):
        return False
    child_key = old_suffix[len(prefix) :]
    if not _is_path_segment(child_key) or "/" in child_key:
        return False
    document = store.read_document(old_breakpoint)
    if not isinstance(document, dict):
        return False
    mapping = _mapping_at(document, map_suffix)
    return mapping is not None and child_key in mapping


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
    if step.rehome_map_suffix is not None:
        generic_rehome(store, step.introduced_pattern, step.rehome_map_suffix, patterns)


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
        raise UnhandledFormatError(_UNREADABLE_VERSION, minimum)
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnhandledFormatError(_UNREADABLE_VERSION, minimum)
    return version


def _stamp(store: DocumentStore, version: int) -> None:
    store.write_document(STORAGE_VERSION_KEY, {"version": version})


def _mapping_at(document: dict[str, JSONValue], map_suffix: str) -> dict[str, JSONValue] | None:
    node: JSONValue = document
    for segment in map_suffix.split("/"):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    if not isinstance(node, dict):
        return None
    return node


def _delete_mapping(document: dict[str, JSONValue], map_suffix: str) -> None:
    segments = map_suffix.split("/")
    node: JSONValue = document
    for segment in segments[:-1]:
        if not isinstance(node, dict):
            return
        node = node[segment]
    if isinstance(node, dict):
        node.pop(segments[-1], None)


def _is_path_segment(key: str) -> bool:
    return key not in ("", ".", "..") and "/" not in key and "\\" not in key
