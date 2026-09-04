"""Hopeless classifier for inference expensive-tier abort.

Evaluated only after cheap exact tiers through ``full_components``. A hard-equality
exact from those tiers wins: the classifier does not fire. On cheap-unsat, any one
disjunct is sufficient for abort. Planet/SB count drops and a warship-count drop
block the scoreboard mine-shaped path (disjunct 1) only. Sticky prior and recent
owner-field observation still abort of either remainder sign.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
)
from api.models.game import TurnInfo


class _WarshipCombo(Protocol):
    warship_delta: int
    score_delta_2x: int


class _WarshipCatalog(Protocol):
    ship_build_combos: Sequence[_WarshipCombo]


MODERATE_RESIDUAL_MAX_POINTS = 11
CHEAP_LADDER_LAST_STEP_ID = "full_components"
EXPENSIVE_TIER_STEP_IDS = frozenset(
    {
        "admit_starbase_defense_posts",
        "torp_escape_tier",
        "full_catalog_exact",
    }
)


@dataclass(frozen=True)
class HopelessRowFacts:
    """Scoreboard/RST facts for one row. Leftover is not stored here -- compute at abort."""

    planet_delta: int
    starbase_delta: int
    sticky_prior: bool
    max_owner_minefield_units: int


@dataclass(frozen=True)
class HopelessAbortDecision:
    abort: bool
    status: str | None = None


def leftover_2x_after_construction_envelope(
    military_delta_2x: int,
    warship_delta: int,
    min_warship_score_delta_2x: int | None = None,
) -> int:
    """Unexplained military after the ship/freighter construction envelope.

    Freighters do not contribute military. When ``warship_delta`` is positive and a
    minimum legal warship fill is known, leftover is observed military minus that
    envelope. Flat or decreasing warship counts leave the observation unchanged;
    a warship-count drop is not mine-shaped at classify time.
    """
    explained_2x = 0
    if warship_delta > 0 and min_warship_score_delta_2x is not None:
        explained_2x = warship_delta * min_warship_score_delta_2x
    return military_delta_2x - explained_2x


def leftover_points(leftover_2x: int) -> int:
    """Absolute leftover in scoreboard points (host 1x units)."""
    return abs(leftover_2x) // 2


def min_warship_score_delta_2x(catalog: _WarshipCatalog | None) -> int | None:
    """Cheapest legal warship fill in the current cheap-tier catalog, if any."""
    if catalog is None:
        return None
    scores = [
        combo.score_delta_2x for combo in catalog.ship_build_combos if combo.warship_delta == 1
    ]
    if not scores:
        return None
    return min(scores)


def max_owner_minefield_units(turn: TurnInfo, owner_id: int) -> int:
    """Largest RST ``units`` among this owner's fields on one turn."""
    if not turn.minefields:
        return 0
    owned = [field.units for field in turn.minefields if field.ownerid == owner_id]
    return max(owned) if owned else 0


def max_owner_minefield_units_in_recent_window(
    *,
    owner_id: int,
    host_turn: int,
    window_turns: int,
    turns_by_number: Mapping[int, TurnInfo],
    exact_host_turns: frozenset[int] = frozenset(),
) -> int:
    """Max owner field size in the recent window, resetting after a cheap exact.

    A host turn persisted as ``exact`` drops N-window carry-forward, including that
    turn's own RST. Later turns may open a new window from their own RST.
    """
    start = max(1, host_turn - window_turns + 1)
    maximum = 0
    for turn_number in range(start, host_turn + 1):
        if turn_number in exact_host_turns:
            maximum = 0
            continue
        turn = turns_by_number.get(turn_number)
        if turn is None:
            continue
        maximum = max(maximum, max_owner_minefield_units(turn, owner_id))
    return maximum


def scoreboard_mine_shaped_path_blocked(
    facts: HopelessRowFacts,
    warship_delta: int,
) -> bool:
    """True when planet, starbase, or warship *count* drops veto the mine-shaped path.

    Race-specific gains (Empire free fighters, Robot lay-gains) are excluded by
    requiring a decrease-shaped leftover; they are not a hard race veto on a true
    decrease (captured tubes and miX exist).
    """
    return facts.planet_delta < 0 or facts.starbase_delta < 0 or warship_delta < 0


def classify_hopeless_abort(
    facts: HopelessRowFacts,
    leftover_2x: int,
    warship_delta: int,
) -> HopelessAbortDecision:
    """Return expensive-tier abort status for a cheap-unsat scoreboard row.

    Mine-contaminated regime (``mine_score_residual``): sticky prior, any owner
    field ``units > 0`` in the recent window, or decrease-shaped leftover beyond
    the moderate floor with mine-plausible counts. Leftover 1-11 with no regime
    signal still aborts as ``moderate_residual``.
    """
    points = leftover_points(leftover_2x)
    recent_owner_field = facts.max_owner_minefield_units > 0
    decrease_beyond_moderate = leftover_2x < 0 and points > MODERATE_RESIDUAL_MAX_POINTS
    mine_shaped_decrease = decrease_beyond_moderate and not scoreboard_mine_shaped_path_blocked(
        facts, warship_delta
    )
    if facts.sticky_prior or recent_owner_field or mine_shaped_decrease:
        return HopelessAbortDecision(abort=True, status=STATUS_MINE_SCORE_RESIDUAL)
    if 1 <= points <= MODERATE_RESIDUAL_MAX_POINTS:
        return HopelessAbortDecision(abort=True, status=STATUS_MODERATE_RESIDUAL)
    return HopelessAbortDecision(abort=False)


def build_hopeless_row_facts(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    sticky_prior: bool = False,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    exact_host_turns: frozenset[int] = frozenset(),
    recent_window_turns: int,
) -> HopelessRowFacts:
    """Assemble row facts from the observation, RST window, and sticky prior."""
    host_turn = turn.settings.turn
    turns_by_number: dict[int, TurnInfo] = {host_turn: turn}
    if load_scoreboard_turn is not None:
        start = max(1, host_turn - recent_window_turns + 1)
        for turn_number in range(start, host_turn):
            loaded = load_scoreboard_turn(turn_number)
            if loaded is not None:
                turns_by_number[turn_number] = loaded
    return HopelessRowFacts(
        planet_delta=observation.planet_delta,
        starbase_delta=observation.starbase_delta,
        sticky_prior=sticky_prior,
        max_owner_minefield_units=max_owner_minefield_units_in_recent_window(
            owner_id=observation.player_id,
            host_turn=host_turn,
            window_turns=recent_window_turns,
            turns_by_number=turns_by_number,
            exact_host_turns=exact_host_turns,
        ),
    )


class _PersistedRowStatus(Protocol):
    status: str


class _InferenceRowReader(Protocol):
    def get_row(
        self, game_id: int, perspective: int, host_turn: int, player_id: int
    ) -> _PersistedRowStatus | None: ...

    def has_mine_residual_sticky_prior(
        self, game_id: int, perspective: int, host_turn: int, player_id: int
    ) -> bool: ...


class _HopelessFactsSession(Protocol):
    observation: InferenceObservation
    turn: TurnInfo
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None
    persistence: _InferenceRowReader | None
    game_id: int
    perspective: int


def exact_host_turns_from_persistence(
    persistence: _InferenceRowReader | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    host_turn: int,
    window_turns: int,
) -> frozenset[int]:
    """Host turns in the window whose persisted row is a cheap-exact win."""
    if persistence is None:
        return frozenset()
    start = max(1, host_turn - window_turns + 1)
    found: set[int] = set()
    for turn_number in range(start, host_turn):
        row = persistence.get_row(game_id, perspective, turn_number, player_id)
        if row is not None and row.status == STATUS_EXACT:
            found.add(turn_number)
    return frozenset(found)


def hopeless_context_for_row(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    sticky_prior: bool = False,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    persistence: _InferenceRowReader | None = None,
    game_id: int | None = None,
    perspective: int | None = None,
    policy_path: Path | None = None,
) -> HopelessRowFacts:
    """Build row facts for one scoreboard row, including sticky and RST window."""
    from api.analytics.military_score_inference.tier_policy import resolve_solver_thresholds

    thresholds = resolve_solver_thresholds(policy_path)
    host_turn = turn.settings.turn
    exact_turns = frozenset()
    resolved_sticky = sticky_prior
    if persistence is not None and game_id is not None and perspective is not None:
        resolved_sticky = persistence.has_mine_residual_sticky_prior(
            game_id, perspective, host_turn, observation.player_id
        )
        exact_turns = exact_host_turns_from_persistence(
            persistence,
            game_id=game_id,
            perspective=perspective,
            player_id=observation.player_id,
            host_turn=host_turn,
            window_turns=thresholds.recent_minefield_observation_turns,
        )
    return build_hopeless_row_facts(
        observation,
        turn,
        sticky_prior=resolved_sticky,
        load_scoreboard_turn=load_scoreboard_turn,
        exact_host_turns=exact_turns,
        recent_window_turns=thresholds.recent_minefield_observation_turns,
    )


def hopeless_row_facts_from_session(session: _HopelessFactsSession) -> HopelessRowFacts:
    """Assemble row facts from a stream session's observation, RST loader, and persist."""
    return hopeless_context_for_row(
        session.observation,
        session.turn,
        load_scoreboard_turn=session.load_scoreboard_turn,
        persistence=session.persistence,
        game_id=session.game_id,
        perspective=session.perspective,
    )
