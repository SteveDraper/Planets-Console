"""Mutable cross-tier state for one policy-ladder row run."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    HullCollisionTwinsAsset,
)
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceSolution,
)
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep


@dataclass
class PolicyLadderState:
    """Mutable cross-tier state for one policy-ladder row run."""

    policy_steps: tuple[InferenceTierPolicyStep, ...]
    policy_steps_attempted: list[str] = field(default_factory=list)
    step_diagnostics: list[dict[str, object]] = field(default_factory=list)
    merged_solutions: list[InferenceSolution] = field(default_factory=list)
    seen_signatures: set[tuple[tuple[str, int], ...]] = field(default_factory=set)
    catalog: ActionCatalog | None = None
    problem: InferenceProblem | None = None
    last_status: str = STATUS_NO_EXACT_SOLUTION
    last_diagnostics: dict[str, object] = field(default_factory=dict)
    resolved_max_solutions: int = 20
    time_limited: bool = False
    band_seeds: list[InferenceSolution] = field(default_factory=list)
    best_band_residual_2x: int | None = None
    prior_combo_ids: frozenset[str] | None = None
    prior_aggregate_action_ids: frozenset[str] | None = None
    ladder_early_stop_reason: str | None = None
    next_step_index: int = 0
    ladder_complete: bool = False
    cancelled: bool = False
    started_at: float = field(default_factory=time.monotonic)
    resolved_mask: ResolvedHullCatalogMask | None = None
    fleet_torp_overlay: FleetTorpOverlay | None = None
    hull_collision_twins: HullCollisionTwinsAsset | None = None
    hull_collision_twins_path: str | None = None
    hull_collision_twins_fell_back: bool = False
    hull_collision_twins_loaded: bool = False
