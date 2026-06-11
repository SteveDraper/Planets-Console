"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from api.analytics.military_score_inference.prior_weights_catalog import (
    GENERIC_FREIGHTER_PRIOR_HULL_ID,
    CategoryComponentLogTables,
    IntLogWeightTable,
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    ResolvedComponentCountTables,
    SlotFillLogWeightTable,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
    ship_limit_band_key,
)

__all__ = [
    "GENERIC_FREIGHTER_PRIOR_HULL_ID",
    "CategoryComponentLogTables",
    "IntLogWeightTable",
    "PriorWeightsCatalog",
    "PriorWeightsDiagnostics",
    "ResolvedComponentCountTables",
    "SlotFillLogWeightTable",
    "resolve_prior_weights_catalog",
    "ship_limit_band_key",
]
