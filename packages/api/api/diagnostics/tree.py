"""Composable diagnostic tree: names, values, per-section timings, and child nodes.

``values`` are **JSON-serializable** in the sense of a finite nested structure: scalars, lists,
and string-keyed dicts (see :class:`JSONValue`). In practice, request root nodes set only
**scalars** (query/path metadata); children may add structured detail (e.g. lists of small
dicts) that still round-trips with :func:`json.dumps` / :meth:`jsonable_encoder` on the BFF.
Timings are wall seconds (``time.perf_counter`` deltas) per named section.
"""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
# Nested JSON-shaped payloads (natively ``json``-encodable, no set/date unless encoded elsewhere).
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class Diagnostics(Protocol):
    """Common surface for enabled diagnostic trees and disabled no-op diagnostics."""

    name: str
    values: MutableMapping[str, JSONValue]
    timings: MutableMapping[str, float]

    @property
    def enabled(self) -> bool:
        """Whether this diagnostics object records observations."""

    def child(self, name: str) -> "Diagnostics":
        """Return a child diagnostics object."""

    def to_dict(self) -> dict[str, Any]:
        """Return the serialized diagnostics tree."""


@dataclass
class DiagnosticNode:
    """One node in a diagnostic tree (typically one instrumented function or a request shell)."""

    name: str
    values: dict[str, JSONValue] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    children: list[DiagnosticNode] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return True

    def child(self, name: str) -> DiagnosticNode:
        """Append and return a child node (e.g. a sub-call)."""
        c = DiagnosticNode(name=name)
        self.children.append(c)
        return c

    def to_dict(self) -> dict[str, Any]:
        """Return a tree dict whose ``values`` values are :class:`JSONValue` (JSON-encodable)."""
        return {
            "name": self.name,
            "values": dict(self.values),
            "timings": dict(self.timings),
            "children": [c.to_dict() for c in self.children],
        }


class _NoopMutableMapping(MutableMapping[str, Any]):
    """Mutable mapping that silently discards writes for disabled diagnostics."""

    def __getitem__(self, key: str) -> Any:
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        pass

    def __delitem__(self, key: str) -> None:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class NoopDiagnosticNode:
    """Disabled diagnostics object with the same recording API as :class:`DiagnosticNode`."""

    name = ""
    values: MutableMapping[str, JSONValue] = _NoopMutableMapping()
    timings: MutableMapping[str, float] = _NoopMutableMapping()

    @property
    def enabled(self) -> bool:
        return False

    def child(self, name: str) -> "NoopDiagnosticNode":
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "values": {}, "timings": {}, "children": []}


NOOP_DIAGNOSTICS = NoopDiagnosticNode()


def request_root_node(
    method: str,
    path: str,
    *,
    path_template: str | None = None,
    **param_values: JSONScalar,
) -> DiagnosticNode:
    """Build the wrapper node for one HTTP request: name + salient request parameters.

    ``path`` should be the logical route (e.g. ``/analytics/connections/map``).
    ``path_template`` if set is stored in ``values`` (e.g. for OpenAPI template paths).

    Kwargs are **scalars** (typical for query and handler labels); :attr:`values` on the
    node still accepts the full :class:`JSONValue` set for any later mutation on children.
    """
    values: dict[str, JSONValue] = dict(param_values)
    if path_template is not None:
        values["pathTemplate"] = path_template
    return DiagnosticNode(name=f"{method} {path}", values=values)


def optional_request_root(
    include: bool,
    method: str,
    path: str,
    *,
    path_template: str | None = None,
    **param_values: JSONScalar,
) -> Diagnostics:
    """Build request diagnostics when enabled; otherwise return a no-op diagnostics object."""
    if not include:
        return NOOP_DIAGNOSTICS
    return request_root_node(method, path, path_template=path_template, **param_values)


@contextmanager
def timed_section(node: Diagnostics, section_name: str) -> Iterator[None]:
    """Record wall time (seconds) for a block in ``node.timings[section_name]``."""
    if not node.enabled:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        node.timings[section_name] = time.perf_counter() - t0
