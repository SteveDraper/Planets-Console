"""Prior aggregate turn for one homeworld evidence refine step."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.homeworld_locator.evidence_ensure import prior_evidence_turn

from tests.test_homeworld_evidence_refine import _load_turn


def test_prior_evidence_turn_names_the_stored_aggregate() -> None:
    base = _load_turn()
    # shell turn, acceleratedturns, baseline turn, expected prior aggregate turn
    cases = (
        (1, 0, 1, None),
        (5, 0, 1, 4),
        (3, 3, 1, 1),
        (4, 3, 1, 3),
        (5, 0, 5, None),
        (6, 0, 5, 5),
        (8, 8, 5, 5),
    )
    for turn_number, accelerated, baseline, expected in cases:
        turn = replace(
            base,
            settings=replace(
                base.settings,
                turn=turn_number,
                acceleratedturns=accelerated,
            ),
        )
        assert prior_evidence_turn(turn, baseline_turn=baseline) == expected
