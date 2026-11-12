"""Runtime remapping of declared compute backends."""

from __future__ import annotations

import sys

from api.compute.profile import ComputeBackend
from api.config import get_config


def process_is_frozen() -> bool:
    """Return True when this process is a PyInstaller frozen executable."""
    return bool(getattr(sys, "frozen", False))


FROZEN_INTERPRETER_REMAP_REASON = (
    "frozen process; InterpreterPoolExecutor cannot import application modules under PyInstaller"
)
CONFIGURED_INTERPRETER_REMAP_REASON = "api.remap_interpreter_backend_to_thread"


def interpreter_remap_reason() -> str | None:
    """Return why declared ``interpreter`` steps run as ``thread``, or None if they run as declared.

    A frozen (PyInstaller) process always remaps, and that reason wins. Otherwise
    ``api.remap_interpreter_backend_to_thread`` remaps, so unpackaged/dev can
    match packaged GIL behaviour.
    """
    if process_is_frozen():
        return FROZEN_INTERPRETER_REMAP_REASON
    if get_config().remap_interpreter_backend_to_thread:
        return CONFIGURED_INTERPRETER_REMAP_REASON
    return None


def effective_compute_backend(backend: ComputeBackend) -> ComputeBackend:
    """Return the backend the worker pool should actually run.

    PyInstaller subinterpreters do not install the frozen importer, so
    ``InterpreterPoolExecutor`` cannot reconstruct application callables
    (``NotShareableError`` / ``BrokenInterpreterPool``). Fleet observation
    stays declared ``interpreter``; a frozen process -- or an unpackaged
    process with ``api.remap_interpreter_backend_to_thread`` -- runs it as
    ``thread``.
    """
    if backend == "interpreter" and interpreter_remap_reason() is not None:
        return "thread"
    return backend
