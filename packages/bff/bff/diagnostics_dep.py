"""Shared FastAPI dependency and helpers for optional request diagnostics (BFF).

Use :data:`IncludeDiagnostics` on any route (GET or POST; pass ``?includeDiagnostics=true`` in
the query string). Build a tree with :func:`optional_request_root`, time work with
:func:`with_timed_child`, then :func:`finish_response`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from api.diagnostics import DiagnosticNode, request_root_node, timed_section
from fastapi import Query
from fastapi.encoders import jsonable_encoder

from bff.diagnostics_http import response_with_diagnostics

# Default is set on the parameter (`= False`), not inside ``Query(...)`` — FastAPI requires
# that when using ``Annotated`` (see dependency analysis in fastapi).
IncludeDiagnostics = Annotated[bool, Query(alias="includeDiagnostics")]

T = TypeVar("T")

JSONScalar = str | int | float | bool | None


def optional_request_root(
    include: bool,
    method: str,
    bff_path: str,
    **param_values: JSONScalar,
) -> DiagnosticNode | None:
    """If ``include`` is True, return the request wrapper node; otherwise ``None``."""
    if not include:
        return None
    return request_root_node(method, bff_path, **param_values)


def with_timed_child(
    root: DiagnosticNode | None,
    child_name: str,
    section: str,
    work: Callable[[], T],
) -> T:
    """Run ``work`` inside ``root.child(child_name)`` with ``timed_section``; if ``root`` is
    None, only ``work`` runs.
    """
    if root is None:
        return work()
    child = root.child(child_name)
    with timed_section(child, section):
        return work()


def to_diagnostic_payload(body: object) -> dict[str, Any]:
    """Coerce a handler result to a dict suitable for merging with ``diagnostics``."""
    if isinstance(body, dict):
        return body
    enc = jsonable_encoder(body)
    if isinstance(enc, dict):
        return enc
    return {"value": enc}


def finish_response(body: object, root: DiagnosticNode | None) -> object:
    """If diagnostics were requested, attach the serialized tree and record MRU; else return
    ``body`` unchanged.
    """
    if root is None:
        return body
    return response_with_diagnostics(to_diagnostic_payload(body), root)
