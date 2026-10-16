"""Opt-in reproduction of a modest planet-defense tier that skips a negative band.

Skipped unless ``SCORES_OUTLIER_REPRO=1``. How to run, and the storage root,
live in ``tests.scores_outlier_repro_harness``.
"""

from __future__ import annotations

from pathlib import Path

from tests.scores_outlier_repro_harness import (
    TURN15_PLAYER38_MODEST_LOADED_WALL_SECONDS,
    TURN15_PLAYER38_MODEST_TIER_INDEX,
    format_outlier_report,
    open_outlier_repro_storage,
    reproduce_admit_ship_outlier,
)


def test_turn15_player38_modest_planet_defense_reproduces_late3_outlier(
    outlier_repro_storage: Path,
) -> None:
    """Turn 15 player 38 planet defense does not enumerate a negative score band.

    The loaded step was 20.8 s while 8 workers were busy. The catalog has no
    ship combos and the observed military score is negative, so the under-explain
    band is skipped instead of searched.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=15,
            player_id=38,
            through_tier_index=TURN15_PLAYER38_MODEST_TIER_INDEX,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN15_PLAYER38_MODEST_LOADED_WALL_SECONDS,
    )
    print(rendered)
    modest = report.tier(TURN15_PLAYER38_MODEST_TIER_INDEX)
    assert modest is not None, f"ladder stopped before tier 5\n{rendered}"
    assert modest.tier_id == "modest_planet_defense", rendered
    assert modest.combo_count == 0, rendered
    assert modest.structural_hits == 0, rendered
    assert modest.outcome == "continue", rendered
    heavy = [
        sample
        for sample in report.solves
        if sample.tier.startswith("5:") and sample.branches >= 10_000
    ]
    assert not heavy, rendered
