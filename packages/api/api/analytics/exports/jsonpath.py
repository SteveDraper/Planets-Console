"""RFC 9535-ish JSONPath subset for analytic export queries."""

from __future__ import annotations

import re
from typing import Any

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[(\d+|\*)\]")


def parse_jsonpath(path: str) -> list[str | int]:
    """Parse a JSONPath selector into traversal steps.

    Supports ``$``, dot names, ``[index]``, and ``[*]``.
    """
    if not path or path == "$":
        return []
    if not path.startswith("$"):
        raise ValueError(f"Unsupported JSONPath root: {path!r}")

    steps: list[str | int] = []
    position = 1
    if position < len(path) and path[position] == ".":
        position += 1

    while position < len(path):
        if path[position] == ".":
            position += 1

        name_match = _NAME.match(path, position)
        if name_match is not None:
            steps.append(name_match.group(0))
            position = name_match.end()
            continue

        index_match = _INDEX.match(path, position)
        if index_match is not None:
            index_token = index_match.group(1)
            steps.append("*" if index_token == "*" else int(index_token))
            position = index_match.end()
            continue

        raise ValueError(f"Invalid JSONPath segment in {path!r} at {path[position:]!r}")

    return steps


def resolve_jsonpath(document: Any, path: str) -> list[Any]:
    """Return all nodes matched by *path* (empty list means zero matches)."""
    try:
        steps = parse_jsonpath(path)
    except ValueError:
        return []
    nodes: list[Any] = [document]
    for step in steps:
        next_nodes: list[Any] = []
        for node in nodes:
            if step == "*":
                if not isinstance(node, list):
                    continue
                next_nodes.extend(node)
                continue
            if isinstance(step, int):
                if not isinstance(node, list) or step < 0 or step >= len(node):
                    continue
                next_nodes.append(node[step])
                continue
            if not isinstance(node, dict) or step not in node:
                continue
            next_nodes.append(node[step])
        nodes = next_nodes
        if not nodes:
            break
    return nodes
