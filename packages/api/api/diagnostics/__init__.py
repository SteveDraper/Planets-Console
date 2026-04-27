"""Request-scoped diagnostic trees for server-side instrumentation (JSON-serializable)."""

from api.diagnostics.tree import (
    NOOP_DIAGNOSTICS,
    DiagnosticNode,
    Diagnostics,
    JSONScalar,
    JSONValue,
    NoopDiagnosticNode,
    optional_request_root,
    request_root_node,
    timed_section,
)

__all__ = [
    "DiagnosticNode",
    "Diagnostics",
    "JSONScalar",
    "JSONValue",
    "NOOP_DIAGNOSTICS",
    "NoopDiagnosticNode",
    "optional_request_root",
    "request_root_node",
    "timed_section",
]
