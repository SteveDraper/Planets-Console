"""Helpers to attach a diagnostic tree to a JSON response and record it in the MRU buffer."""

from __future__ import annotations

from api.diagnostics import DiagnosticNode

from bff.diagnostics_buffer import get_diagnostics_buffer


def response_with_diagnostics(
    body: dict,
    root: DiagnosticNode,
) -> dict:
    """Return a copy of ``body`` with a ``diagnostics`` key, and push to the MRU buffer."""
    d = root.to_dict()
    get_diagnostics_buffer().append(summary=root.name, tree=d)
    out = {**body, "diagnostics": d}
    return out
