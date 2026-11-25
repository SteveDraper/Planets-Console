"""Per-analytic export service bundles for scores."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.military_score_inference.hull_catalog_mask import (
    ResolvedHullCatalogMask,
    resolve_hull_catalog_mask,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores.hull_mask_overrides import HullMaskOverrides
from api.analytics.scores_assets import ANALYTIC_ID
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


def _default_stream_token_resolver(scope: InferenceStreamScope) -> str | None:
    controller = controller_for_scope(scope)
    return controller.stream_token if controller is not None else None


@dataclass(frozen=True)
class ScoresExportContext:
    """Inference services used by scores export ensure and materialization.

    ``mask_overrides`` is the storage backend's one hull mask override store
    (``hull_mask_overrides_for``). Its revision is part of the scores epoch, so
    every bundle for a backend must carry that same instance.
    """

    mask_overrides: HullMaskOverrides = field(kw_only=True)
    scheduler: InferenceRowScheduler = field(default_factory=get_inference_row_scheduler)
    resolve_stream_token: Callable[[InferenceStreamScope], str | None] = field(
        default_factory=lambda: _default_stream_token_resolver
    )
    persistence: InferenceRowPersistenceService | None = None

    def resolve_hull_catalog_mask(
        self, turn: TurnInfo, game_id: int, player_id: int
    ) -> ResolvedHullCatalogMask:
        """The player's effective hull catalog mask on ``turn``, with their stored override."""
        user_override = self.mask_overrides.snapshot(game_id, player_id).user_override
        return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=user_override)


def resolve_scores_services(ctx: AnalyticQueryContext) -> ScoresExportContext:
    services = export_service_for(ctx, ANALYTIC_ID, ScoresExportContext)
    if services is not None:
        return services

    injected = ctx.export_services.get(ANALYTIC_ID)
    if injected is None:
        raise RuntimeError(
            f"Scores export requires {ANALYTIC_ID!r} in ctx.export_services; "
            "inject ScoresExportContext via TurnAnalyticService or test helpers."
        )
    raise RuntimeError(
        f"Scores export_services[{ANALYTIC_ID!r}] must be ScoresExportContext, "
        f"got {type(injected).__name__}."
    )
