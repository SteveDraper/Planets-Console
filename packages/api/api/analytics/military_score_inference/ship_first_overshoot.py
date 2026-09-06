"""Ship-first overshoot overlay for the mine-contaminated regime (design §3.10).

Runtime plan for prefix steps through ``admit_ship_torpedoes``: military window
``observed + slack < explained <= observed + cap_2x``, not inference score band.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.hopeless_classifier import HopelessRowFacts
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.prior_mining.mine_stock import owned_active_minefields
from api.analytics.military_score_inference.worthwhile_remainder_bound import (
    worthwhile_remainder_bound_for_turn,
)
from api.models.game import TurnInfo

SHIP_FIRST_PREFIX_LAST_STEP_ID = "admit_ship_torpedoes"
SHIP_FIRST_PREFIX_STOP_REASON = "ship_first_prefix"
PLANET_OR_STARBASE_POST_STEP_IDS = frozenset(
    {
        "modest_planet_defense",
        "admit_starbase_defense_posts",
    }
)


@dataclass(frozen=True)
class ShipFirstOvershootPlan:
    """Whether the in-regime prefix uses the overshoot window instead of band retry."""

    active: bool
    skip_leftover_0_exact: bool
    cap_2x: int | None
    overshoot_window_empty: bool

    @property
    def run_overshoot(self) -> bool:
        return self.active and not self.overshoot_window_empty and self.cap_2x is not None


def current_turn_has_owner_minefields(turn: TurnInfo, player_id: int) -> bool:
    """Viewpoint-RST owner fields with ``units > 0`` (observed-stock floor evidence)."""
    return bool(owned_active_minefields(turn, player_id))


def resolve_ship_first_overshoot_plan(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    hopeless_context: HopelessRowFacts | None,
) -> ShipFirstOvershootPlan:
    """Activate the overlay when current-turn owner fields, sticky, or N-window fire."""
    skip_leftover_0 = current_turn_has_owner_minefields(turn, observation.player_id)
    known_regime = False
    if hopeless_context is not None:
        known_regime = (
            hopeless_context.sticky_prior or hopeless_context.max_owner_minefield_units > 0
        )
    active = skip_leftover_0 or known_regime
    if not active:
        return ShipFirstOvershootPlan(
            active=False,
            skip_leftover_0_exact=False,
            cap_2x=None,
            overshoot_window_empty=True,
        )
    bound = worthwhile_remainder_bound_for_turn(observation, turn)
    if bound is None:
        return ShipFirstOvershootPlan(
            active=True,
            skip_leftover_0_exact=skip_leftover_0,
            cap_2x=None,
            overshoot_window_empty=True,
        )
    return ShipFirstOvershootPlan(
        active=True,
        skip_leftover_0_exact=skip_leftover_0,
        cap_2x=bound.cap_2x,
        overshoot_window_empty=bound.overshoot_window_empty,
    )


def leftover_military_2x(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> int:
    """Raw overshoot ``explained - observed`` in solver 2x (post-sort leftover)."""
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    explained = 0
    for action in solution.actions:
        catalog_action = actions_by_id.get(action.action_id)
        if catalog_action is None:
            continue
        explained += catalog_action.score_delta_2x * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id.get(ship_build.combo_id)
        if combo is None:
            continue
        explained += combo.score_delta_2x * ship_build.count
    return explained - observation.military_delta_2x
