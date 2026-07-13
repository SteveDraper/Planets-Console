"""Conditional collision-hull-widen step helpers for scores inference (#226)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    HullCollisionTwinsAsset,
    admitted_high_hull_ids_for_observation,
    load_hull_collision_twins_for_game_category,
    military_change_from_delta_2x,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep
from api.concepts.game_category import GameCategory
from api.models.game import TurnInfo


@dataclass(frozen=True)
class CollisionHullWidenPlan:
    """Resolved twin overlay for one ``collision_hull_widen`` step attempt."""

    twin_asset_path: str | None
    twin_fell_back_to_standard: bool
    emitted_low_hull_ids: tuple[int, ...]
    admitted_high_hull_ids: tuple[int, ...]
    skipped: bool
    military_change: int
    policy_step: InferenceTierPolicyStep

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "collisionHullWiden": {
                "twinAssetPath": self.twin_asset_path,
                "twinFellBackToStandard": self.twin_fell_back_to_standard,
                "emittedLowHullIds": list(self.emitted_low_hull_ids),
                "admittedHighHullIds": list(self.admitted_high_hull_ids),
                "skipped": self.skipped,
                "militaryChange": self.military_change,
            }
        }


def emitted_low_hull_ids_from_solutions(
    solutions: list[InferenceSolution] | tuple[InferenceSolution, ...],
    *,
    catalog: ActionCatalog | None,
) -> frozenset[int]:
    """Collect hull ids from exact solutions already held before the widen step."""
    hull_ids: set[int] = set()
    combos_by_id = (
        {combo.combo_id: combo for combo in catalog.ship_build_combos}
        if catalog is not None
        else {}
    )
    for solution in solutions:
        for ship_build in solution.ship_builds:
            if ship_build.hull_id is not None:
                hull_ids.add(ship_build.hull_id)
                continue
            combo = combos_by_id.get(ship_build.combo_id)
            if combo is not None:
                hull_ids.add(combo.hull_id)
    return frozenset(hull_ids)


def policy_step_with_included_hull_ids(
    policy_step: InferenceTierPolicyStep,
    hull_ids: frozenset[int] | tuple[int, ...],
) -> InferenceTierPolicyStep:
    include_ids = tuple(sorted(set(hull_ids)))
    hull_filter = replace(policy_step.filters.hulls, include_component_ids=include_ids)
    filters = replace(policy_step.filters, hulls=hull_filter)
    return replace(policy_step, filters=filters)


def resolve_collision_hull_widen_plan(
    policy_step: InferenceTierPolicyStep,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
    merged_solutions: list[InferenceSolution],
    prior_catalog: ActionCatalog | None,
    resolved_mask: ResolvedHullCatalogMask | None,
    twins_asset: HullCollisionTwinsAsset | None,
    twins_asset_path: Path | None,
    twins_fell_back: bool,
) -> CollisionHullWidenPlan:
    """Resolve twin admission for ``collision_hull_widen``; skip when no partners."""
    military_change = military_change_from_delta_2x(observation.military_delta_2x)
    emitted = emitted_low_hull_ids_from_solutions(merged_solutions, catalog=prior_catalog)
    buildable = buildable_hull_ids_for_player(
        turn,
        observation.player_id,
        resolved_mask=resolved_mask,
    )
    admitted: frozenset[int] = frozenset()
    if twins_asset is not None and emitted:
        admitted = admitted_high_hull_ids_for_observation(
            twins_asset,
            emitted_low_hull_ids=emitted,
            military_change=military_change,
            buildable_hull_ids=buildable,
        )
    skipped = not admitted
    resolved_step = (
        policy_step if skipped else policy_step_with_included_hull_ids(policy_step, admitted)
    )
    return CollisionHullWidenPlan(
        twin_asset_path=str(twins_asset_path) if twins_asset_path is not None else None,
        twin_fell_back_to_standard=twins_fell_back,
        emitted_low_hull_ids=tuple(sorted(emitted)),
        admitted_high_hull_ids=tuple(sorted(admitted)),
        skipped=skipped,
        military_change=military_change,
        policy_step=resolved_step,
    )


def load_twins_for_turn(
    turn: TurnInfo,
    *,
    base_dir: Path | None = None,
) -> tuple[HullCollisionTwinsAsset | None, Path | None, bool]:
    category = GameCategory.from_game_settings(
        turn.settings,
        player_count=len(turn.players),
    )
    if category == GameCategory.UNKNOWN:
        category = GameCategory.STANDARD
    return load_hull_collision_twins_for_game_category(category, base_dir=base_dir)
