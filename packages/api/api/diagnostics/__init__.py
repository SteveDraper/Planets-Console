"""Request-scoped diagnostic trees for server-side instrumentation (JSON-serializable)."""

from api.diagnostics.tree import DiagnosticNode, request_root_node, timed_section

__all__ = [
    "DiagnosticNode",
    "request_root_node",
    "timed_section",
]
