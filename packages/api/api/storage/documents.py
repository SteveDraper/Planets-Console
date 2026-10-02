"""Breakpoint documents shared by the file and ephemeral backends.

A logical path is one breakpoint document plus an optional in-document suffix.
A longer breakpoint is its own document. It is not a nested key of the shorter
document.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BreakpointPatterns,
    is_navigable_prefix,
    is_prefix_of_longer_breakpoint,
    resolve_breakpoint,
)
from api.storage.path_utils import (
    deep_copy_value,
    ensure_ancestors,
    list_children,
    parse_index_segment,
    resolve_parent_and_segment,
    resolve_path,
)


def partition_logical_tree(
    root: dict[str, JSONValue],
    patterns: BreakpointPatterns,
) -> dict[str, JSONValue]:
    """Split a nested logical tree into one value per breakpoint document."""
    documents: dict[str, JSONValue] = {}

    def place(node: JSONValue, path: str) -> None:
        try:
            breakpoint_path, _suffix = resolve_breakpoint(path, patterns)
        except ValidationError:
            if isinstance(node, dict):
                for key, child in node.items():
                    place(child, f"{path}/{key}" if path else key)
            return
        if breakpoint_path == path:
            documents[path] = _extract_document(node, path, path)
            return
        if isinstance(node, dict):
            for key, child in node.items():
                place(child, f"{path}/{key}")

    def _extract_document(node: JSONValue, document_path: str, node_path: str) -> JSONValue:
        if not isinstance(node, dict):
            return deep_copy_value(node)
        kept: dict[str, JSONValue] = {}
        for key, child in node.items():
            child_path = f"{node_path}/{key}"
            try:
                child_breakpoint, _suffix = resolve_breakpoint(child_path, patterns)
            except ValidationError:
                kept[key] = deep_copy_value(child)
                continue
            if child_breakpoint != document_path:
                place(child, child_path)
                continue
            kept[key] = _extract_document(child, document_path, child_path)
        return kept

    if isinstance(root, dict):
        for key, child in root.items():
            place(child, key)
    return documents


def document_after_put(
    document: JSONValue | None,
    suffix: str | None,
    value: JSONValue,
    *,
    breakpoint_path: str,
) -> JSONValue:
    """Return the breakpoint document after storing ``value`` at ``suffix``.

    ``suffix`` ``None`` replaces the document. A missing document starts as ``{}``
    when the write is nested.
    """
    if suffix is None:
        return value
    copied: JSONValue = {} if document is None else deep_copy_value(document)
    if not isinstance(copied, dict):
        raise ValidationError(
            f"Cannot create nested path under non-object document: {breakpoint_path!r}"
        )
    parent, segment, is_array_index = ensure_ancestors(copied, suffix)
    if is_array_index:
        idx = parse_index_segment(segment)
        if not isinstance(parent, list):
            raise ValidationError("Array index segment in path but parent is not an array")
        if idx == len(parent):
            parent.append(value)
        elif 0 <= idx < len(parent):
            parent[idx] = value
        else:
            n = len(parent)
            if idx < 0:
                idx += n
            if idx == n:
                parent.append(value)
            elif 0 <= idx < n:
                parent[idx] = value
            else:
                raise NotFoundError(f"Array index out of range: {segment}")
    else:
        if not isinstance(parent, dict):
            raise NotFoundError("Parent is not an object")
        parent[segment] = value
    return copied


def document_after_delete(document: JSONValue, suffix: str) -> JSONValue:
    """Return ``document`` after removing in-document ``suffix``."""
    updated = deep_copy_value(document)
    parent, segment, is_array_index = resolve_parent_and_segment(updated, suffix)
    if is_array_index:
        idx = parse_index_segment(segment)
        if not isinstance(parent, list):
            raise ValidationError("Array index segment in path but parent is not an array")
        if idx < 0:
            idx += len(parent)
        if idx < 0 or idx >= len(parent):
            raise NotFoundError(f"Array index out of range: {segment}")
        parent.pop(idx)
    else:
        if not isinstance(parent, dict):
            raise NotFoundError("Parent is not an object")
        if segment not in parent:
            raise NotFoundError(f"Path does not exist: {segment!r}")
        del parent[segment]
    return updated


def child_names_for_prefix(paths: Iterable[str], prefix: str) -> list[str]:
    """Next-hop names implied by breakpoint paths under ``prefix``.

    Raises ``NotFoundError`` when no stored breakpoint lies under ``prefix``.
    """
    prefix_segments = [] if prefix == "" else prefix.split("/")
    depth = len(prefix_segments)
    names: set[str] = set()
    for path in paths:
        segments = path.split("/")
        if segments[:depth] != prefix_segments:
            continue
        if len(segments) <= depth:
            continue
        names.add(segments[depth])
    if not names:
        raise NotFoundError(f"Path does not exist: {prefix!r}")
    return sorted(names)


def list_logical(
    path: str,
    *,
    patterns: BreakpointPatterns,
    document_exists: Callable[[str], bool],
    load_document: Callable[[str], JSONValue],
    child_names: Callable[[str], list[str]],
) -> list[str]:
    """List the next hop under ``path`` using the same rules as the file backend."""
    if not is_navigable_prefix(path, patterns):
        raise ValidationError(f"Unregistered store path prefix: {path!r}")
    if path == "":
        return child_names("")
    try:
        breakpoint_path, suffix = resolve_breakpoint(path, patterns)
    except ValidationError:
        return child_names(path)
    if is_prefix_of_longer_breakpoint(path, patterns) and (
        suffix is not None or not document_exists(breakpoint_path)
    ):
        return child_names(path)
    exists = document_exists(breakpoint_path)
    if not exists:
        raise NotFoundError(f"Path does not exist: {path!r}")
    document = load_document(breakpoint_path)
    if suffix is None:
        return list_children(document)
    node = resolve_path(document, suffix)
    return list_children(node)


def read_logical(document: JSONValue, suffix: str | None) -> JSONValue:
    """Return a deep copy of the value at ``suffix`` inside ``document``."""
    if suffix is None:
        return deep_copy_value(document)
    return deep_copy_value(resolve_path(document, suffix))
