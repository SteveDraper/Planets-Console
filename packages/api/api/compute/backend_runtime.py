"""Runtime remapping of declared compute backends."""

from __future__ import annotations

import sys

from api.compute.profile import ComputeBackend


def process_is_frozen() -> bool:
    """Return True when this process is a PyInstaller frozen executable."""
    return bool(getattr(sys, "frozen", False))


def effective_compute_backend(backend: ComputeBackend) -> ComputeBackend:
    """Return the backend the worker pool should actually run.

    PyInstaller subinterpreters do not install the frozen importer, so
    ``InterpreterPoolExecutor`` cannot reconstruct application callables
    (``NotShareableError`` / ``BrokenInterpreterPool``). Fleet observation
    stays declared ``interpreter``; a frozen process runs it as ``thread``.
    """
    if backend == "interpreter" and process_is_frozen():
        return "thread"
    return backend
