"""Central registration of analytic table-stream registries in the catalog.

Analytic registry modules own attach/detach/reschedule only. This module
catalogs those registries so fleet/scores never import ``registry_catalog``.

The stream connect entry (``scoped_connect``) calls it before the stream's
controller is attached, outside every lock, so a catalog scan never registers
or imports anything.
"""

from __future__ import annotations

from api.analytics.fleet.fleet_table_stream_registry import get_fleet_table_stream_registry
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
)
from api.streaming.table_stream.registry_catalog import register_table_stream_registry


def ensure_table_stream_registries_registered() -> None:
    """Catalog the fleet and scores table-stream registries; repeat calls change nothing."""
    register_table_stream_registry("fleet", get_fleet_table_stream_registry())
    register_table_stream_registry("scores", get_inference_table_stream_registry())
