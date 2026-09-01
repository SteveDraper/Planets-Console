"""Public-scoreboard seed for mixed gift+build pairing (#387).

Ground-truth notes from game 683364 host turn 15, viewpoint player 1
(Federation). Solver tests must not use RST ship identity; these notes
document why the public numbers look the way they do.

RST (artifact only, not a solver input): Fed Nebula #36 at (2537, 1663)
with friendly code ``gs5`` changed owner 1→5. Same host turn Fed built
Nova #124 and Large Deep Space Freighter #129; Privateer shows two new
Meteors (#51, #130) plus the Nebula.
"""

from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
)
from api.models.player import Score

# Scoreboard 1x militarychange values from 683364 turn 15.
PRIVATEER_PLAYER_ID = 5
FEDERATION_PLAYER_ID = 1
BIRDS_PLAYER_ID = 3
VIEWPOINT_OWNER_ID = FEDERATION_PLAYER_ID


def _row(
    player_id: int,
    *,
    warship: int,
    freighter: int,
    military_change_1x: int,
    starbases: int,
    priority_point_delta: int,
    planet_delta: int = 0,
    starbase_delta: int = 0,
) -> PublicScoreboardRow:
    return PublicScoreboardRow(
        player_id=player_id,
        warship_delta=warship,
        freighter_delta=freighter,
        military_delta_2x=2 * military_change_1x,
        starbases=starbases,
        priority_point_delta=priority_point_delta,
        planet_delta=planet_delta,
        starbase_delta=starbase_delta,
    )


def privateer_observation() -> InferenceObservation:
    row = privateer_row()
    return InferenceObservation(
        player_id=row.player_id,
        turn=15,
        military_delta_2x=row.military_delta_2x,
        warship_delta=row.warship_delta,
        freighter_delta=row.freighter_delta,
        priority_point_delta=row.priority_point_delta,
        starbases_owned=row.starbases,
        is_after_ship_limit=False,
        planet_delta=row.planet_delta,
        starbase_delta=row.starbase_delta,
    )


def privateer_row() -> PublicScoreboardRow:
    """Player 5: built 2 (idle-dock), net +3 → arrived ≥ 1."""
    return _row(
        PRIVATEER_PLAYER_ID,
        warship=3,
        freighter=0,
        military_change_1x=6674,
        starbases=2,
        priority_point_delta=0,
        planet_delta=1,
    )


def federation_row() -> PublicScoreboardRow:
    """Player 1: built 2, net +1 → departed ≥ 1. Class of the gift is public-ambiguous."""
    return _row(
        FEDERATION_PLAYER_ID,
        warship=0,
        freighter=1,
        military_change_1x=2919,
        starbases=3,
        priority_point_delta=2,
    )


def birds_row() -> PublicScoreboardRow:
    """Player 3: k=1, net 0 → excess_out 1."""
    return _row(
        BIRDS_PLAYER_ID,
        warship=0,
        freighter=0,
        military_change_1x=5448,
        starbases=1,
        priority_point_delta=0,
    )


def privateer_peer_rows() -> tuple[PublicScoreboardRow, ...]:
    return (federation_row(), birds_row())


def _score(
    owner_id: int,
    *,
    shipchange: int,
    freighterchange: int,
    militarychange: int,
    starbases: int,
    prioritypointchange: int,
    planetchange: int = 0,
    starbasechange: int = 0,
) -> Score:
    return Score(
        id=owner_id,
        dateadded="",
        ownerid=owner_id,
        accountid=owner_id,
        capitalships=0,
        freighters=0,
        planets=0,
        starbases=starbases,
        militaryscore=0,
        inventoryscore=0,
        prioritypoints=0,
        turn=15,
        percent=0.0,
        victoryscore=0,
        victorybonuses="",
        technologicalaccumulator=0,
        widestreach=0,
        greatestwarrior=0,
        happybeings=0,
        shipchange=shipchange,
        freighterchange=freighterchange,
        planetchange=planetchange,
        starbasechange=starbasechange,
        militarychange=militarychange,
        inventorychange=0,
        prioritypointchange=prioritypointchange,
        percentchange=0.0,
        victoryscorechange=0,
    )


def privateer_peer_scores() -> tuple[Score, ...]:
    """Public scores including the viewpoint Federation row (not solved)."""
    return (
        _score(
            FEDERATION_PLAYER_ID,
            shipchange=0,
            freighterchange=1,
            militarychange=2919,
            starbases=3,
            prioritypointchange=2,
        ),
        _score(
            BIRDS_PLAYER_ID,
            shipchange=0,
            freighterchange=0,
            militarychange=5448,
            starbases=1,
            prioritypointchange=0,
        ),
        _score(
            PRIVATEER_PLAYER_ID,
            shipchange=3,
            freighterchange=0,
            militarychange=6674,
            starbases=2,
            prioritypointchange=0,
            planetchange=1,
        ),
    )
