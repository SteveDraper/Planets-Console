"""Opt-in reproduction of an incoming-warship floor that skips the torpedo search.

Skipped unless ``SCORES_OUTLIER_REPRO=1``. How to run, and the storage root,
live in ``tests.scores_outlier_repro_harness``.
"""

from __future__ import annotations

from pathlib import Path

from tests.scores_outlier_repro_harness import (
    OUTLIER_TIER_INDEX,
    TURN8_PLAYER9_ADMIT_LOADED_WALL_SECONDS,
    format_outlier_report,
    open_outlier_repro_storage,
    reproduce_admit_ship_outlier,
)


def test_turn8_player9_incoming_warship_floor_skips_torpedo_plateau(
    outlier_repro_storage: Path,
) -> None:
    """Turn 8 player 9 emits donor transfers from hull floors and does not search.

    The loaded admit step was 125.9 s on a saturated pool. Idle, that same
    search spent the full 1.0 deterministic allowance (about 0.39 s, 50692
    branches, 20 torpedo-plateau hits). With donor hull floors the ladder
    stops on the first tier.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=8,
            player_id=9,
            through_tier_index=OUTLIER_TIER_INDEX,
            load_counterparty_fleets=True,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN8_PLAYER9_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    assert len(report.tiers) == 1, rendered
    first = report.tiers[0]
    assert first.index == 0, rendered
    assert first.combo_count == 0, rendered
    assert first.stopped_reason == "incoming_warship_floor", rendered
    assert first.deterministic_time == 0.0, rendered
    assert first.wall_seconds < 1.0, rendered
    assert report.solves == [], rendered
    assert report.solution_action_ids == [
        ("acquired:warship:from:14",),
        ("acquired:warship:from:16",),
        ("acquired:warship:from:48",),
    ], rendered
    assert report.solution_families == ["mine_overshoot", "mine_overshoot", "mine_overshoot"]
