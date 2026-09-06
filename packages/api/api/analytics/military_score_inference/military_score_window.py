"""Tagged CP-SAT military-score window (exact, band, or overshoot)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_MILITARY_LHS = "sum(scoreDelta2x * count)"


@dataclass(frozen=True)
class ExactMilitaryScoreWindow:
    """Partition slack two-sided band, or hard equality when slack is 0."""

    kind: Literal["exact"] = "exact"


@dataclass(frozen=True, kw_only=True)
class BandMilitaryScoreWindow:
    """Under-explain retry: explained >= observed - alpha (no upper bound)."""

    kind: Literal["band"] = "band"
    alpha: int

    def __post_init__(self) -> None:
        if self.alpha <= 0:
            raise ValueError("band military window alpha must be positive")


@dataclass(frozen=True, kw_only=True)
class OvershootMilitaryScoreWindow:
    """Ship-first window: observed + slack < explained <= observed + cap_2x.

    ``cap_2x`` is None when no remainder bound is available (empty window).
    A finite cap at or below partition slack is also empty (lower > upper).
    """

    kind: Literal["overshoot"] = "overshoot"
    cap_2x: int | None = None


MilitaryScoreWindow = (
    ExactMilitaryScoreWindow | BandMilitaryScoreWindow | OvershootMilitaryScoreWindow
)


@dataclass(frozen=True)
class MilitaryWindowBounds:
    """Inclusive CP-SAT bounds for ``sum(scoreDelta2x * count)``.

    ``equal`` is set only for exact equality (no slack). Otherwise ``lower`` /
    ``upper`` may each be None to leave that side unbounded.
    """

    lower: int | None
    upper: int | None
    equal: int | None


def military_window_alpha(window: MilitaryScoreWindow) -> int:
    if isinstance(window, BandMilitaryScoreWindow):
        return window.alpha
    return 0


def military_window_overshoot_cap_2x(window: MilitaryScoreWindow) -> int | None:
    if isinstance(window, OvershootMilitaryScoreWindow):
        return window.cap_2x
    return None


def military_window_bounds(
    window: MilitaryScoreWindow,
    *,
    rhs: int,
    slack: int,
) -> MilitaryWindowBounds:
    """Single encoding of the military window as CP-SAT bounds."""
    if isinstance(window, OvershootMilitaryScoreWindow):
        upper = rhs + window.cap_2x if window.cap_2x is not None else rhs + slack
        return MilitaryWindowBounds(lower=rhs + slack + 1, upper=upper, equal=None)
    if isinstance(window, BandMilitaryScoreWindow):
        return MilitaryWindowBounds(lower=rhs - window.alpha, upper=None, equal=None)
    if slack > 0:
        return MilitaryWindowBounds(lower=rhs - slack, upper=rhs + slack, equal=None)
    return MilitaryWindowBounds(lower=None, upper=None, equal=rhs)


def applied_military_equality(
    window: MilitaryScoreWindow,
    *,
    military_delta_2x: int,
    partition_slack_2x: int,
) -> str:
    bounds = military_window_bounds(
        window,
        rhs=military_delta_2x,
        slack=partition_slack_2x,
    )
    if bounds.equal is not None:
        return f"{_MILITARY_LHS} == {bounds.equal}"
    if bounds.lower is not None and bounds.upper is not None:
        return f"{bounds.lower} <= {_MILITARY_LHS} <= {bounds.upper}"
    if bounds.lower is not None:
        return f"{_MILITARY_LHS} >= {bounds.lower}"
    if bounds.upper is not None:
        return f"{_MILITARY_LHS} <= {bounds.upper}"
    raise ValueError("military window produced no CP-SAT bound")
