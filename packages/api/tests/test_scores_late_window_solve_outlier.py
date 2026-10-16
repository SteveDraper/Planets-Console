"""Opt-in reproduction of a late-window ladder through full_components.

Skipped unless ``SCORES_OUTLIER_REPRO=1``. How to run, and the storage root,
live in ``tests.scores_outlier_repro_harness``.
"""

from __future__ import annotations

from pathlib import Path

from tests.scores_outlier_repro_harness import (
    OUTLIER_TIER_ID,
    OUTLIER_TIER_INDEX,
    TURN10_PLAYER51_ADMIT_LOADED_WALL_SECONDS,
    TURN10_PLAYER51_THROUGH_TIER_INDEX,
    format_outlier_report,
    open_outlier_repro_storage,
    reproduce_admit_ship_outlier,
)


def test_turn10_player51_solve_reproduces_late_outlier(
    outlier_repro_storage: Path,
) -> None:
    """Idle reproduction of the turn 10 player 51 ladder through full_components.

    Loaded walls while 8 workers were busy: admit_ship 30.8 s, planet defense
    12.0 s, full_components 13.0 s. The row's completed node stopped on tier 6.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=10,
            player_id=51,
            through_tier_index=TURN10_PLAYER51_THROUGH_TIER_INDEX,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN10_PLAYER51_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.wall_seconds >= 1.0, rendered
    assert admit.combo_count >= 10_000, rendered
    full_components = report.tier(TURN10_PLAYER51_THROUGH_TIER_INDEX)
    assert full_components is not None, f"ladder stopped before tier 6\n{rendered}"
    assert full_components.tier_id == "full_components", rendered
