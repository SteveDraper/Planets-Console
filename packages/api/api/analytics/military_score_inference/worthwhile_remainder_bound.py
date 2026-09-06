"""Solve-time worthwhile remainder bound from mine-stock histograms (design §3.9).

Loads ``mine_stock_{category}.yaml`` and converts exact-turn p90 stock to leftover
2x. Does not attach the cap to CP-SAT; that is the overshoot-constraint phase.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import floor
from pathlib import Path

from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.prior_mining.mine_stock import (
    MineStockAsset,
    load_mine_stock_for_category,
    owned_active_minefields,
)
from api.analytics.turn_roster import player_by_id, players_by_id
from api.concepts.game_category import GameCategory
from api.concepts.minefield_decay import (
    equal_split_field_units,
    lost_units_after_default_decay,
)
from api.models.game import TurnInfo

REMAINDER_BOUND_PERCENTILE = 0.90
REMAINDER_BOUND_MIXTURE_N0 = 20
# Solver 2x leftover from lost mine units: 27 host points / 100 units, doubled.
LEFTOVER_MILITARY_2X_PER_LOST_UNIT = 54 / 100


@dataclass(frozen=True)
class WorthwhileRemainderBound:
    """Real leftover bound plus the integer CP-SAT cap (constraint unwired)."""

    bound_2x: float
    cap_2x: int
    overshoot_window_empty: bool
    empirical_leftover_2x: float
    mixed_leftover_2x: float
    interpolant_leftover_2x: float
    observed_floor_2x: float
    n_total: int
    mixture_weight: float
    p90_total_units: int | None
    p90_field_count: int | None

    def diagnostics_payload(self) -> dict[str, object]:
        return {
            "bound2x": self.bound_2x,
            "cap2x": self.cap_2x,
            "overshootWindowEmpty": self.overshoot_window_empty,
            "empiricalLeftover2x": self.empirical_leftover_2x,
            "mixedLeftover2x": self.mixed_leftover_2x,
            "interpolantLeftover2x": self.interpolant_leftover_2x,
            "observedFloor2x": self.observed_floor_2x,
            "nTotal": self.n_total,
            "mixtureWeight": self.mixture_weight,
            "p90TotalUnits": self.p90_total_units,
            "p90FieldCount": self.p90_field_count,
        }


def leftover_military_2x_from_lost_units(lost_units: int) -> float:
    """Convert decayed mine units to leftover military in solver 2x (``54L/100``)."""
    if lost_units <= 0:
        return 0.0
    return LEFTOVER_MILITARY_2X_PER_LOST_UNIT * lost_units


def leftover_military_2x_equal_split(total_units: int, field_count: int) -> float:
    """Equal-split default decay leftover for a (total units, field count) pair."""
    lost = sum(
        lost_units_after_default_decay(units)
        for units in equal_split_field_units(total_units, field_count)
        if units > 0
    )
    return leftover_military_2x_from_lost_units(lost)


def leftover_military_2x_per_field(field_units: Sequence[int]) -> float:
    """Exact per-field default decay leftover (observed-stock floor)."""
    lost = sum(lost_units_after_default_decay(units) for units in field_units if units > 0)
    return leftover_military_2x_from_lost_units(lost)


def compute_worthwhile_remainder_bound(
    asset: MineStockAsset,
    *,
    race_id: int,
    host_turn: int,
    observed_field_units: Sequence[int],
    slack_2x: int,
) -> WorthwhileRemainderBound:
    """p90 convert, remainder-bound turn mixture, then observed-stock floor."""
    race_turns = asset.histograms.get(race_id, {})
    cell = race_turns.get(host_turn, {})
    n_total = _n_total(cell)
    empirical = _empirical_leftover_2x(cell)
    p90_units, p90_fields = _positive_stock_p90_pair(cell)
    interpolant = _isotonic_interpolant(race_turns, host_turn)
    weight = n_total / (n_total + REMAINDER_BOUND_MIXTURE_N0)
    mixed = weight * empirical + (1.0 - weight) * interpolant
    observed = leftover_military_2x_per_field(observed_field_units)
    bound_2x = max(mixed, observed)
    cap_2x = floor(bound_2x)
    return WorthwhileRemainderBound(
        bound_2x=bound_2x,
        cap_2x=cap_2x,
        overshoot_window_empty=cap_2x <= slack_2x,
        empirical_leftover_2x=empirical,
        mixed_leftover_2x=mixed,
        interpolant_leftover_2x=interpolant,
        observed_floor_2x=observed,
        n_total=n_total,
        mixture_weight=weight,
        p90_total_units=p90_units,
        p90_field_count=p90_fields,
    )


def worthwhile_remainder_bound_for_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    base_dir: Path | None = None,
) -> WorthwhileRemainderBound | None:
    """Load the category mine-stock asset and compute the bound for this row.

    Missing player or missing required yaml returns ``None`` -- no synthetic empty
    asset. ``GameCategory.UNKNOWN`` loads standard, same as ``load_twins_for_turn``.
    """
    try:
        player = player_by_id(turn, observation.player_id)
    except ValueError:
        return None
    category = GameCategory.from_game_settings(
        turn.settings,
        player_count=len(players_by_id(turn)),
    )
    if category == GameCategory.UNKNOWN:
        category = GameCategory.STANDARD
    try:
        asset, _, _ = load_mine_stock_for_category(category, base_dir=base_dir)
    except FileNotFoundError:
        return None
    owned = owned_active_minefields(turn, observation.player_id)
    return compute_worthwhile_remainder_bound(
        asset,
        race_id=player.raceid,
        host_turn=turn.settings.turn,
        observed_field_units=tuple(field.units for field in owned),
        slack_2x=observation.military_partition_slack_2x,
    )


def worthwhile_remainder_bound_diagnostics(bound: WorthwhileRemainderBound) -> dict[str, object]:
    return {"worthwhileRemainderBound": bound.diagnostics_payload()}


def _n_total(cell: Mapping[str, Mapping[int, float]]) -> int:
    return int(sum(cell.get("totalUnits", {}).values()))


def _positive_stock_p90_pair(
    cell: Mapping[str, Mapping[int, float]],
) -> tuple[int | None, int | None]:
    return (
        _histogram_percentile(cell.get("totalUnits", {}), drop_zero=True),
        _histogram_percentile(cell.get("fieldCount", {}), drop_zero=True),
    )


def _empirical_leftover_2x(cell: Mapping[str, Mapping[int, float]]) -> float:
    p90_units, p90_fields = _positive_stock_p90_pair(cell)
    if p90_units is None or p90_fields is None or p90_fields <= 0 or p90_units <= 0:
        return 0.0
    return leftover_military_2x_equal_split(p90_units, p90_fields)


def _histogram_percentile(
    counts: Mapping[int, float],
    *,
    drop_zero: bool,
) -> int | None:
    items = [
        (magnitude, weight)
        for magnitude, weight in counts.items()
        if weight > 0 and not (drop_zero and magnitude == 0)
    ]
    if not items:
        return None
    items.sort()
    total = sum(weight for _, weight in items)
    threshold = REMAINDER_BOUND_PERCENTILE * total
    cumulative = 0.0
    for magnitude, weight in items:
        cumulative += weight
        if cumulative >= threshold:
            return magnitude
    return items[-1][0]


def _isotonic_interpolant(
    race_turns: Mapping[int, Mapping[str, Mapping[int, float]]],
    host_turn: int,
) -> float:
    knots = _weighted_isotonic_knots(race_turns)
    if not knots:
        return 0.0
    if host_turn <= knots[0][0]:
        return knots[0][1]
    if host_turn >= knots[-1][0]:
        return knots[-1][1]
    for index in range(1, len(knots)):
        left_turn, left_leftover = knots[index - 1]
        right_turn, right_leftover = knots[index]
        if host_turn > right_turn:
            continue
        span = right_turn - left_turn
        if span <= 0:
            return right_leftover
        fraction = (host_turn - left_turn) / span
        return left_leftover + fraction * (right_leftover - left_leftover)
    return knots[-1][1]


def _weighted_isotonic_knots(
    race_turns: Mapping[int, Mapping[str, Mapping[int, float]]],
) -> list[tuple[int, float]]:
    """Same-race leftover vs T, PAVA-pooled, non-decreasing, weighted by n_total."""
    samples: list[tuple[int, float, int]] = []
    for host_turn, cell in race_turns.items():
        weight = _n_total(cell)
        if weight <= 0:
            continue
        samples.append((host_turn, _empirical_leftover_2x(cell), weight))
    samples.sort(key=lambda item: item[0])
    if not samples:
        return []
    # Each pool: turns, weight, weighted leftover sum.
    blocks: list[tuple[list[int], float, float]] = []
    for host_turn, leftover, weight in samples:
        blocks.append(([host_turn], float(weight), leftover * weight))
        while len(blocks) >= 2:
            prev_turns, prev_weight, prev_sum = blocks[-2]
            cur_turns, cur_weight, cur_sum = blocks[-1]
            prev_mean = prev_sum / prev_weight
            cur_mean = cur_sum / cur_weight
            if prev_mean <= cur_mean:
                break
            blocks[-2:] = [(prev_turns + cur_turns, prev_weight + cur_weight, prev_sum + cur_sum)]
    knots: list[tuple[int, float]] = []
    for turns, weight, weighted_sum in blocks:
        leftover = weighted_sum / weight
        for host_turn in turns:
            knots.append((host_turn, leftover))
    knots.sort(key=lambda item: item[0])
    return knots
