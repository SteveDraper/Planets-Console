"""Resolved inference build prior catalog and query surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from api.analytics.military_score_inference.hull_category import (
    InferenceHullCategory,
    resolve_inference_hull_category,
    slot_fill_pattern,
)
from api.analytics.military_score_inference.models import (
    ProbabilityBinBounds,
    ProbabilityBucket,
    probability_buckets_from_bin_bounds,
)
from api.analytics.military_score_inference.prior_weights_asset import ShipLimitBand
from api.models.components import Beam, Engine, Hull, Torpedo

# Synthetic hull id in prior-weight asset hull tables (not a buildable in-game hull).
# Freighter combo likelihood uses this pseudo-hull's marginal log weight when no
# per-combo override is present; see prior_weights_standard.yaml hulls.999999.
GENERIC_FREIGHTER_PRIOR_HULL_ID = 999999

IntLogWeightTable: TypeAlias = dict[int, int]
SlotFillLogWeightTable: TypeAlias = dict[str, int]


@dataclass(frozen=True)
class ResolvedComponentCountTables:
    engines: IntLogWeightTable
    beams: IntLogWeightTable
    torpedoes: IntLogWeightTable
    slot_fill: SlotFillLogWeightTable = field(default_factory=dict)


CategoryComponentLogTables: TypeAlias = dict[
    InferenceHullCategory,
    ResolvedComponentCountTables,
]

__all__ = [
    "GENERIC_FREIGHTER_PRIOR_HULL_ID",
    "CategoryComponentLogTables",
    "IntLogWeightTable",
    "PriorWeightsCatalog",
    "PriorWeightsDiagnostics",
    "ResolvedComponentCountTables",
    "SlotFillLogWeightTable",
]


@dataclass(frozen=True)
class PriorWeightsDiagnostics:
    category_id: str
    asset_path: str
    asset_version: int
    game_category_rules_version: int
    fell_back_to_standard: bool
    ship_limit_band: ShipLimitBand
    race_id_used: int | None

    def to_payload(self) -> dict[str, object]:
        return {
            "categoryId": self.category_id,
            "assetPath": self.asset_path,
            "assetVersion": self.asset_version,
            "gameCategoryRulesVersion": self.game_category_rules_version,
            "fellBackToStandard": self.fell_back_to_standard,
            "shipLimitBand": self.ship_limit_band,
            "raceIdUsed": self.race_id_used,
        }


@dataclass(frozen=True)
class PriorWeightsCatalog:
    diagnostics: PriorWeightsDiagnostics
    _hull_log_weights: dict[int, int]
    _component_tables: CategoryComponentLogTables
    _aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]]
    _combo_log_overrides: dict[str, int]
    _hull_log_overrides: dict[int, int]

    def hull_marginal_log_weight(self, hull_id: int, *, default_weight: int = 0) -> int:
        hull_override = self._hull_log_overrides.get(hull_id)
        if hull_override is not None:
            return hull_override
        return self._hull_log_weights.get(hull_id, default_weight)

    def _resolved_combo_log_weight(
        self,
        *,
        combo_id: str,
        composed_weight: int,
    ) -> int:
        override = self._combo_log_overrides.get(combo_id)
        if override is not None:
            return override
        return composed_weight

    def freighter_probability_weight(self, *, combo_id: str, default_weight: int) -> int:
        """Freighter likelihood: combo override, else pseudo-hull marginal.

        See ``GENERIC_FREIGHTER_PRIOR_HULL_ID``.
        """
        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=self.hull_marginal_log_weight(
                GENERIC_FREIGHTER_PRIOR_HULL_ID,
                default_weight=default_weight,
            ),
        )

    def combo_probability_weight(
        self,
        *,
        combo_id: str,
        hull: Hull,
        engine: Engine,
        beam: Beam | None,
        torpedo: Torpedo | None,
        beam_count: int,
        launcher_count: int,
    ) -> int:
        hull_weight = self.hull_marginal_log_weight(hull.id)

        hull_category = resolve_inference_hull_category(
            hull,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
        category_tables = self._component_tables[hull_category]
        fill = slot_fill_pattern(hull, beam_count=beam_count, launcher_count=launcher_count)

        component_weight = 0
        component_weight += category_tables.engines.get(engine.id, 0)
        if beam is not None and beam_count > 0:
            component_weight += category_tables.beams.get(beam.id, 0)
        if torpedo is not None and launcher_count > 0:
            component_weight += category_tables.torpedoes.get(torpedo.id, 0)
        component_weight += category_tables.slot_fill.get(fill, 0)

        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=hull_weight + component_weight,
        )

    def probability_buckets_for_action(
        self,
        action_id: str,
        bin_bounds: tuple[ProbabilityBinBounds, ...],
    ) -> tuple[ProbabilityBucket, ...]:
        marginal_weights = self._aggregate_bucket_marginal_weights.get(action_id)
        if marginal_weights is None:
            raise ValueError(
                f"incomplete prior: missing histogram marginal weights for aggregate action "
                f"{action_id!r}"
            )
        if len(marginal_weights) != len(bin_bounds):
            raise ValueError(f"prior bucket count for {action_id} does not match solver bins")
        return probability_buckets_from_bin_bounds(bin_bounds, marginal_weights)
