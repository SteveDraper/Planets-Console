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

IntLogWeightTable: TypeAlias = dict[int, int]
SlotFillLogWeightTable: TypeAlias = dict[str, int]
CategoryHullLogTables: TypeAlias = dict[InferenceHullCategory, IntLogWeightTable]
CategoryLogWeightTable: TypeAlias = dict[InferenceHullCategory, int]


def _required_log_weight(table: dict[int | str, int], key: int | str, *, field_name: str) -> int:
    weight = table.get(key)
    if weight is None:
        raise ValueError(f"incomplete prior: missing {field_name} weight for {key!r}")
    return weight


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
    "CategoryComponentLogTables",
    "CategoryHullLogTables",
    "CategoryLogWeightTable",
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
    _category_log_weights: CategoryLogWeightTable
    _hull_log_weights_by_category: CategoryHullLogTables
    _component_tables: CategoryComponentLogTables
    _aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]]
    _combo_log_overrides: dict[str, int]
    _hull_log_overrides: dict[int, int]
    _generic_freighter_log_weight: int | None = None

    def category_marginal_log_weight(self, hull_category: InferenceHullCategory) -> int:
        weight = self._category_log_weights.get(hull_category)
        if weight is None:
            raise ValueError(
                f"incomplete prior: missing category marginal weight for {hull_category!r}"
            )
        return weight

    def hull_marginal_log_weight(
        self,
        hull_id: int,
        *,
        hull_category: InferenceHullCategory,
        default_weight: int | None = None,
    ) -> int:
        hull_override = self._hull_log_overrides.get(hull_id)
        if hull_override is not None:
            return hull_override
        category_table = self._hull_log_weights_by_category.get(hull_category)
        if category_table is None:
            if default_weight is not None:
                return default_weight
            raise ValueError(
                f"incomplete prior: missing hull marginal table for category {hull_category!r}"
            )
        hull_weight = category_table.get(hull_id)
        if hull_weight is not None:
            return hull_weight
        if default_weight is not None:
            return default_weight
        raise ValueError(
            f"incomplete prior: missing hull marginal weight for {hull_id!r} "
            f"in category {hull_category!r}"
        )

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

    def freighter_probability_weight(self, *, combo_id: str) -> int:
        """Freighter likelihood for the solver's generic freighter combo."""
        if self._generic_freighter_log_weight is None:
            raise ValueError("incomplete prior: missing generic freighter marginal weight")
        composed_weight = self.category_marginal_log_weight("true_freighter")
        composed_weight += self._generic_freighter_log_weight
        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=composed_weight,
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
        hull_category = resolve_inference_hull_category(
            hull,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
        category_tables = self._component_tables[hull_category]
        fill = slot_fill_pattern(hull, beam_count=beam_count, launcher_count=launcher_count)

        composed_weight = self.category_marginal_log_weight(hull_category)
        composed_weight += self.hull_marginal_log_weight(hull.id, hull_category=hull_category)
        composed_weight += _required_log_weight(
            category_tables.engines,
            engine.id,
            field_name=f"{hull_category}.engines",
        )
        if beam is not None and beam_count > 0:
            composed_weight += _required_log_weight(
                category_tables.beams,
                beam.id,
                field_name=f"{hull_category}.beams",
            )
        if torpedo is not None and launcher_count > 0:
            composed_weight += _required_log_weight(
                category_tables.torpedoes,
                torpedo.id,
                field_name=f"{hull_category}.torpedoes",
            )
        if category_tables.slot_fill:
            composed_weight += _required_log_weight(
                category_tables.slot_fill,
                fill,
                field_name=f"{hull_category}.slotFill",
            )

        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=composed_weight,
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
