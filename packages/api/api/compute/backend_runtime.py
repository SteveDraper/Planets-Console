"""Runtime remapping of declared compute backends."""

from __future__ import annotations

import sys

from api.compute.profile import ComputeBackend
from api.config import get_config


def process_is_frozen() -> bool:
    """Return True when this process is a PyInstaller frozen executable."""
    return bool(getattr(sys, "frozen", False))


def should_remap_interpreter_backend_to_thread() -> bool:
    """Return whether declared ``interpreter`` steps must run as ``thread``.

    True when this process is frozen (PyInstaller) or when
    ``api.remap_interpreter_backend_to_thread`` is set so unpackaged/dev can
    match packaged GIL behaviour.
    """
    return process_is_frozen() or get_config().remap_interpreter_backend_to_thread


def effective_compute_backend(backend: ComputeBackend) -> ComputeBackend:
    """Return the backend the worker pool should actually run.

    PyInstaller subinterpreters do not install the frozen importer, so
    ``InterpreterPoolExecutor`` cannot reconstruct application callables
    (``NotShareableError`` / ``BrokenInterpreterPool``). Fleet observation
    stays declared ``interpreter``; a frozen process -- or an unpackaged
    process with ``api.remap_interpreter_backend_to_thread`` -- runs it as
    ``thread``.
    """
    if backend == "interpreter" and should_remap_interpreter_backend_to_thread():
        return "thread"
    return backend
