"""Compute diagnostics public surface."""

from api.compute.diagnostics.controller import (
    compute_diagnostics_enabled,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.snapshot import snapshot_to_wire

__all__ = [
    "ShellContextKey",
    "compute_diagnostics_enabled",
    "get_compute_diagnostics_controller",
    "reset_compute_diagnostics_for_tests",
    "snapshot_to_wire",
]
