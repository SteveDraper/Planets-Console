"""Central registration of analytic table-stream registries for diagnostics.

Analytic registry modules own attach/detach/reschedule only. Diagnostics
introspection registers those registries here so fleet/scores never import
``registry_catalog``.
"""

from __future__ import annotations

from api.analytics.fleet.fleet_table_stream_registry import get_fleet_table_stream_registry
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
)
from api.streaming.table_stream.registry_catalog import register_table_stream_registry

_registered = False


def ensure_table_stream_registries_registered() -> None:
    """Register known table-stream registries once for diagnostics snapshots."""
    global _registered
    if _registered:
        return
    register_table_stream_registry("fleet", get_fleet_table_stream_registry())
    register_table_stream_registry("scores", get_inference_table_stream_registry())
    _registered = True


def reset_table_stream_registry_bootstrap_for_tests() -> None:
    global _registered
    _registered = False
