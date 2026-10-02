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
    ``remove_parent`` deletes that parent after the children are written. When it
    is false, the map is removed and the parent is written back.
    ``holds_retired_path``, when set, reports whether a copied-in parent still
    contains the requested breakpoint. Re-home residue is checked either way.
    """

    version: int
    introduced_pattern: tuple[str, ...]
    structural_handler: StructuralHandler | None = None
    rehome_map_suffix: str | None = None
    remove_parent: bool = False
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
    *,
    remove_parent: bool = False,
) -> None:
    """Move each child of ``map_suffix`` onto ``introduced_pattern``.

    Each real child key is resolved as ``{parent}/{map_suffix}/{child}`` against
    the full breakpoint registry and again with ``introduced_pattern`` removed.
    When ``remove_parent`` is true and the map is present, children are written
    and the parent document is deleted, including when the map is empty.
    Otherwise the map is removed and the parent is written back.
    """
    reduced = tuple(pattern for pattern in patterns if pattern != introduced_pattern)
    paths = [path for path in store.iter_document_paths() if path != STORAGE_VERSION_KEY]
    for path in paths:
        prefix = _rehome_child_prefix(path, map_suffix, introduced_pattern)
        if prefix is None or not store.has_document(path):
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
            destination = f"{prefix}/{child_key}"
            if not _child_is_rehome_target(
                path,
                map_suffix,
                child_key,
                destination,
                introduced_pattern,
                patterns,
                reduced,
            ):
                continue
            store.write_document(destination, deep_copy_value(child_value))
        if remove_parent:
            store.remove_document(path)
            continue
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
        if _retired_document_holds_requested_path(
            store,
            step,
            old_breakpoint,
            old_suffix,
            breakpoint_path,
        ):
            previous = step.version - 1
            found = "unversioned" if previous < 1 else str(previous)
            return UnhandledFormatError(found, str(step.version))
    return None


def _retired_document_holds_requested_path(
    store: DocumentStore,
    step: StorageMigration,
    old_breakpoint: str,
    old_suffix: str | None,
    breakpoint_path: str,
) -> bool:
    if _rehome_child_still_present(
        store,
        old_breakpoint,
        old_suffix,
        step.rehome_map_suffix,
    ):
        return True
    holds_path = step.holds_retired_path
    if holds_path is None:
        return False
    return holds_path(store.read_document(old_breakpoint), breakpoint_path)


def _rehome_child_still_present(
    store: DocumentStore,
    old_breakpoint: str,
    old_suffix: str | None,
    map_suffix: str | None,
) -> bool:
    if map_suffix is None or old_suffix is None:
        return False
    child_key = _child_key_in_rehome_suffix(old_suffix, map_suffix)
    if child_key is None:
        return False
    document = store.read_document(old_breakpoint)
    if not isinstance(document, dict):
        return False
    mapping = _mapping_at(document, map_suffix)
    return mapping is not None and child_key in mapping


def _child_key_in_rehome_suffix(old_suffix: str, map_suffix: str) -> str | None:
    """Return the map key named by a retired logical suffix.

    Scores leaves ``{map_suffix}/{child}`` on the shorter breakpoint. Fleet's
    player id is the whole suffix, because the map name stays inside the parent.
    """
    prefix = f"{map_suffix}/"
    if old_suffix.startswith(prefix):
        child_key = old_suffix[len(prefix) :]
    elif "/" not in old_suffix:
        child_key = old_suffix
    else:
        return None
    if not _is_path_segment(child_key) or "/" in child_key:
        return None
    return child_key


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
        generic_rehome(
            store,
            step.introduced_pattern,
            step.rehome_map_suffix,
            patterns,
            remove_parent=step.remove_parent,
        )


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


def _rehome_child_prefix(
    parent_path: str,
    map_suffix: str,
    introduced_pattern: tuple[str, ...],
) -> str | None:
    """Return the path prefix each map child is written under.

    The prefix is the parent when the introduced breakpoint adds only the child
    segment (fleet ``.../fleet/{playerId}``). It is ``{parent}/{map_suffix}``
    when that map name is itself a path segment (scores ``inference_rows``).
    """
    if len(introduced_pattern) < 2 or introduced_pattern[-1] != "*":
        return None
    parent_pattern = introduced_pattern[:-1]
    if pattern_matches_breakpoint(parent_pattern, parent_path):
        return parent_path
    map_path = f"{parent_path}/{map_suffix}"
    if pattern_matches_breakpoint(parent_pattern, map_path):
        return map_path
    return None


def _child_is_rehome_target(
    parent_path: str,
    map_suffix: str,
    child_key: str,
    destination: str,
    introduced_pattern: tuple[str, ...],
    patterns: BreakpointPatterns,
    reduced: BreakpointPatterns,
) -> bool:
    """Return whether ``child_key`` moves from ``parent_path`` onto ``destination``.

    ``{parent}/{map_suffix}/{child}`` is resolved on both registries. That path
    is the new document when the map name is a path segment. Fleet keeps the
    map name inside the retired document, so ``destination`` is checked on its
    own once the map path still resolves to the parent.
    """
    map_logical = f"{parent_path}/{map_suffix}/{child_key}"
    mapped = _resolved_breakpoints(map_logical, patterns, reduced)
    if mapped is None:
        return False
    new_breakpoint, new_suffix, old_breakpoint = mapped
    if old_breakpoint != parent_path:
        return False
    if new_breakpoint == map_logical and new_suffix is None:
        return destination == map_logical and pattern_matches_breakpoint(
            introduced_pattern,
            new_breakpoint,
        )
    moved = _resolved_breakpoints(destination, patterns, reduced)
    if moved is None:
        return False
    dest_breakpoint, dest_suffix, retired_breakpoint = moved
    return (
        dest_breakpoint == destination
        and dest_suffix is None
        and retired_breakpoint == parent_path
        and pattern_matches_breakpoint(introduced_pattern, dest_breakpoint)
    )


def _resolved_breakpoints(
    logical_path: str,
    patterns: BreakpointPatterns,
    reduced: BreakpointPatterns,
) -> tuple[str, str | None, str] | None:
    """Return ``(new_breakpoint, new_suffix, old_breakpoint)`` for ``logical_path``."""
    try:
        new_breakpoint, new_suffix = resolve_breakpoint(logical_path, patterns)
        old_breakpoint, _old_suffix = resolve_breakpoint(logical_path, reduced)
    except ValidationError:
        return None
    return new_breakpoint, new_suffix, old_breakpoint


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
