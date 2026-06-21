"""Per-analytic export service bundles for scores."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.models.game import TurnInfo
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService


@dataclass(frozen=True)
class ScoresExportContext:
    """Inference services used by scores export ensure and materialization."""

    persistence: InferenceRowPersistenceService | None = None
    scheduler: InferenceRowScheduler | None = None
    resolve_hull_catalog_mask: Callable[[TurnInfo, int], ResolvedHullCatalogMask | None] | None = (
        None
    )
