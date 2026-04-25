"""Composable diagnostic tree: names, values, per-section timings, and child nodes.

Values must be JSON-friendly atomics: ``str | int | float | bool | None``.
Timings are wall seconds (``time.perf_counter`` deltas) per named section.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

JSONScalar = str | int | float | bool | None


@dataclass
class DiagnosticNode:
    """One node in a diagnostic tree (typically one instrumented function or a request shell)."""

    name: str
    values: dict[str, JSONScalar] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    children: list[DiagnosticNode] = field(default_factory=list)

    def child(self, name: str) -> DiagnosticNode:
        """Append and return a child node (e.g. a sub-call)."""
        c = DiagnosticNode(name=name)
        self.children.append(c)
        return c

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly nested dict."""
        return {
            "name": self.name,
            "values": dict(self.values),
            "timings": dict(self.timings),
            "children": [c.to_dict() for c in self.children],
        }


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
    """
    values: dict[str, JSONScalar] = dict(param_values)
    if path_template is not None:
        values["pathTemplate"] = path_template
    return DiagnosticNode(name=f"{method} {path}", values=values)


@contextmanager
def timed_section(node: DiagnosticNode, section_name: str) -> Iterator[None]:
    """Record wall time (seconds) for a block in ``node.timings[section_name]``."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        node.timings[section_name] = time.perf_counter() - t0
