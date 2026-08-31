"""Public scoreboard pairing fingerprints for ship transfer families.

Other players' public ``shipchange`` / ``freighterchange`` / ``militarychange``
are observations on this row's still-per-row solve. Not a joint CP-SAT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.accelerated_start import (
    SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
)
from api.analytics.military_score_inference.models import InferenceObservation

TransferFamily = Literal["gift", "trade", "acquired"]

# Each row's public military score is floored independently, so a single row's
# ``militarychange`` can be off by one 2x unit; a two-row comparison accumulates
# the fuzz from both rows.
_PER_ROW_MILITARY_SLACK_2X = SCOREBOARD_MILITARY_PARTITION_SLACK_2X
_TWO_ROW_MILITARY_SLACK_2X = 2 * SCOREBOARD_MILITARY_PARTITION_SLACK_2X


@dataclass(frozen=True)
class PublicScoreboardRow:
    player_id: int
    warship_delta: int
    freighter_delta: int
    military_delta_2x: int


@dataclass(frozen=True)
class PairingMatch:
    family: TransferFamily
    counterparty_player_id: int
    warship_delta: int
    freighter_delta: int
    counterparty_military_delta_2x: int


@dataclass(frozen=True)
class PublicScoreboardPairing:
    matches: tuple[PairingMatch, ...]
    unmatched_warship_drop: int
    unmatched_freighter_drop: int


def public_scoreboard_row_from_observation(
    observation: InferenceObservation,
) -> PublicScoreboardRow:
    return PublicScoreboardRow(
        player_id=observation.player_id,
        warship_delta=observation.warship_delta,
        freighter_delta=observation.freighter_delta,
        military_delta_2x=observation.military_delta_2x,
    )


def classify_public_scoreboard_pairing(
    this_row: PublicScoreboardRow,
    other_rows: tuple[PublicScoreboardRow, ...],
) -> PublicScoreboardPairing:
    """Classify gift / trade / acquired matches and unmatched count drops."""
    matches: list[PairingMatch] = []
    for other in other_rows:
        if other.player_id == this_row.player_id:
            continue
        trade = _trade_match(this_row, other)
        if trade is not None:
            matches.append(trade)
            continue
        gift = _gift_match(this_row, other)
        if gift is not None:
            matches.append(gift)
            continue
        acquired = _acquired_match(this_row, other)
        if acquired is not None:
            matches.append(acquired)

    gifted_warships = sum(
        -match.warship_delta
        for match in matches
        if match.family == "gift" and match.warship_delta < 0
    )
    gifted_freighters = sum(
        -match.freighter_delta
        for match in matches
        if match.family == "gift" and match.freighter_delta < 0
    )
    unmatched_warship_drop = max(0, -this_row.warship_delta - gifted_warships)
    unmatched_freighter_drop = max(0, -this_row.freighter_delta - gifted_freighters)
    if any(match.family == "trade" for match in matches):
        unmatched_warship_drop = 0
        unmatched_freighter_drop = 0
    return PublicScoreboardPairing(
        matches=tuple(matches),
        unmatched_warship_drop=unmatched_warship_drop,
        unmatched_freighter_drop=unmatched_freighter_drop,
    )


def _net_ship_delta(row: PublicScoreboardRow) -> int:
    return row.warship_delta + row.freighter_delta


def _trade_match(this_row: PublicScoreboardRow, other: PublicScoreboardRow) -> PairingMatch | None:
    """Count-flat swap: military swap and/or warship↔freighter column flip."""
    this_net = _net_ship_delta(this_row)
    other_net = _net_ship_delta(other)
    if this_net != 0 or other_net != 0:
        return None
    class_flip = (
        this_row.warship_delta != 0
        and this_row.freighter_delta == -this_row.warship_delta
        and other.warship_delta == -this_row.warship_delta
        and other.freighter_delta == -this_row.freighter_delta
    )
    # Requiring movement beyond the two-row slack keeps zero-noise rows (both
    # within rounding fuzz of 0) from spuriously matching each other as trades.
    military_swap = (
        this_row.warship_delta == 0
        and this_row.freighter_delta == 0
        and abs(this_row.military_delta_2x) > _TWO_ROW_MILITARY_SLACK_2X
        and abs(this_row.military_delta_2x + other.military_delta_2x) <= _TWO_ROW_MILITARY_SLACK_2X
        and other.warship_delta == 0
        and other.freighter_delta == 0
    )
    if not class_flip and not military_swap:
        return None
    return PairingMatch(
        family="trade",
        counterparty_player_id=other.player_id,
        warship_delta=this_row.warship_delta,
        freighter_delta=this_row.freighter_delta,
        counterparty_military_delta_2x=other.military_delta_2x,
    )


def _gift_match(
    this_row: PublicScoreboardRow,
    other: PublicScoreboardRow,
) -> PairingMatch | None:
    """Outgoing count drop with a compatible +count / +military on another row."""
    if _net_ship_delta(this_row) >= 0:
        return None
    warship_out = this_row.warship_delta < 0 and other.warship_delta > 0
    freighter_out = this_row.freighter_delta < 0 and other.freighter_delta > 0
    if not warship_out and not freighter_out:
        return None
    if not _military_compatible_transfer(this_row, other, outgoing=True):
        return None
    return PairingMatch(
        family="gift",
        counterparty_player_id=other.player_id,
        warship_delta=(-min(-this_row.warship_delta, other.warship_delta) if warship_out else 0),
        freighter_delta=(
            -min(-this_row.freighter_delta, other.freighter_delta) if freighter_out else 0
        ),
        counterparty_military_delta_2x=other.military_delta_2x,
    )


def _acquired_match(
    this_row: PublicScoreboardRow,
    other: PublicScoreboardRow,
) -> PairingMatch | None:
    """Incoming count with a compatible drop on another row -- not a ship build combo."""
    if _net_ship_delta(this_row) <= 0:
        return None
    warship_in = this_row.warship_delta > 0 and other.warship_delta < 0
    freighter_in = this_row.freighter_delta > 0 and other.freighter_delta < 0
    if not warship_in and not freighter_in:
        return None
    if not _military_compatible_transfer(this_row, other, outgoing=False):
        return None
    return PairingMatch(
        family="acquired",
        counterparty_player_id=other.player_id,
        warship_delta=(min(this_row.warship_delta, -other.warship_delta) if warship_in else 0),
        freighter_delta=(
            min(this_row.freighter_delta, -other.freighter_delta) if freighter_in else 0
        ),
        counterparty_military_delta_2x=other.military_delta_2x,
    )


def _military_compatible_transfer(
    this_row: PublicScoreboardRow,
    other: PublicScoreboardRow,
    *,
    outgoing: bool,
) -> bool:
    """Public militarychange signs match an ownership transfer, not two independent builds.

    Sign tests tolerate per-row floor rounding: a row within the per-row slack of 0
    counts as flat. Freighter-only transfers may be flat on both rows. Warship
    transfers require opposite-sign military beyond the slack (or a flat counterparty
    only when this row is also flat, e.g. the freighter side of a mixed drop).
    """
    this_m = this_row.military_delta_2x
    other_m = other.military_delta_2x
    slack = _PER_ROW_MILITARY_SLACK_2X
    if outgoing:
        return (
            this_m <= slack
            and other_m >= -slack
            and not (this_m < -slack and abs(other_m) <= slack)
        )
    return this_m >= -slack and other_m <= slack and not (this_m > slack and abs(other_m) <= slack)
