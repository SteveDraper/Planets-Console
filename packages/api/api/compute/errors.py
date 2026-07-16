"""Compute-orchestrator error types."""

from __future__ import annotations


class ComputeScopeAbortedError(RuntimeError):
    """In-flight compute scope intentionally aborted (e.g. scores row-run cancel).

    On the process-wide singleton DAG, aborting a scope must not cascade
    ``failed`` into dependents (fleet waiting on scores). Dependents stay
    ``waiting_deps`` until a later submit recreates and completes the scope.
    """
