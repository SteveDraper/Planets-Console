"""Path resolution for the logical JSON store.

Paths are slash-separated; segments may be object keys or @N for array index.
Raises NotFoundError, ValidationError from api.errors.
"""
from __future__ import annotations

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue


def parse_index_segment(segment: str) -> int:
    """Parse @N or @-N. Raises ValidationError if not valid. Call only when segment.startswith('@')."""
    suffix = segment[1:]
    try:
        return int(suffix)
    except ValueError:
        raise ValidationError(f"Invalid path segment (expected @integer): {segment!r}")


def resolve_path(root: JSONValue, path: str) -> JSONValue:
    """Resolve path from root. Returns the node at path.

    Raises:
        ValidationError: malformed @ segment or indexing into non-array
        NotFoundError: missing key or index out of range
    """
    if not path or path.strip() == "":
        return root
    segments = [s for s in path.split("/") if s]
    node: JSONValue = root
    for i, seg in enumerate(segments):
        if seg.startswith("@"):
            idx = parse_index_segment(seg)
            if not isinstance(node, list):
                raise ValidationError(
                    f"Path segment {seg!r} denotes array index but parent is not an array"
                )
            n = len(node)
            if idx < 0:
                idx += n
            if idx < 0 or idx >= n:
                raise NotFoundError(f"Array index out of range: {seg} (length {n})")
            node = node[idx]
        else:
            if not isinstance(node, dict):
                raise NotFoundError(
                    f"Path segment {seg!r} denotes object key but parent is not an object"
                )
            if seg not in node:
                raise NotFoundError(f"Path does not exist: {seg!r}")
            node = node[seg]
    return node


def resolve_parent_and_segment(root: JSONValue, path: str) -> tuple[JSONValue, str, bool]:
    """Resolve to the parent node and the final segment (key or @index).

    Returns (parent, final_segment, is_array_index).
    For root path or empty path, returns (root, "", False) and the "node" is root.
    """
    if not path or path.strip() == "":
        return (root, "", False)
    segments = [s for s in path.split("/") if s]
    if len(segments) == 1:
        return (root, segments[0], segments[0].startswith("@"))
    parent_path = "/".join(segments[:-1])
    parent = resolve_path(root, parent_path)
    last = segments[-1]
    return (parent, last, last.startswith("@"))


def ensure_ancestors(root: dict[str, JSONValue], path: str) -> tuple[dict[str, JSONValue] | list[JSONValue], str, bool]:
    """Ensure all ancestors exist as objects along path; return (parent, final_segment, is_array_index).

    Only object keys are created; array index segments must already exist.
    Root must be a dict. Returns the parent container and the last segment.
    """
    if not path or path.strip() == "":
        return (root, "", False)
    segments = [s for s in path.split("/") if s]
    node: JSONValue = root
    for i, seg in enumerate(segments[:-1]):
        if seg.startswith("@"):
            idx = parse_index_segment(seg)
            if not isinstance(node, list):
                raise ValidationError(
                    f"Path segment {seg!r} denotes array index but parent is not an array"
                )
            n = len(node)
            if idx < 0:
                idx += n
            if idx < 0 or idx >= n:
                raise NotFoundError(f"Array index out of range: {seg}")
            node = node[idx]
        else:
            if not isinstance(node, dict):
                raise NotFoundError("Ancestor is not an object")
            if seg not in node:
                node[seg] = {}
                node = node[seg]
            else:
                node = node[seg]
    last = segments[-1]
    is_index = last.startswith("@")
    if is_index and isinstance(node, list):
        return (node, last, True)
    if is_index:
        raise ValidationError("Array index segment in path but parent is not an array")
    if not isinstance(node, dict):
        raise NotFoundError("Parent is not an object")
    return (node, last, False)


def list_children(node: JSONValue) -> list[str]:
    """Return next-hop segment names: object keys or @0..@(n-1) for arrays."""
    if isinstance(node, dict):
        return sorted(node.keys())
    if isinstance(node, list):
        return [f"@{i}" for i in range(len(node))]
    return []


def deep_copy_value(value: JSONValue) -> JSONValue:
    """Deep copy a JSON value (dict/list/primitive)."""
    if isinstance(value, dict):
        return {k: deep_copy_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [deep_copy_value(v) for v in value]
    return value


def validate_no_reserved_at_keys(value: JSONValue) -> None:
    """Raise ValidationError if any object key in the tree starts with @ (reserved)."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith("@"):
                raise ValidationError(
                    f"Reserved key: object keys must not start with '@' (found {k!r})"
                )
            validate_no_reserved_at_keys(v)
    elif isinstance(value, list):
        for item in value:
            validate_no_reserved_at_keys(item)
