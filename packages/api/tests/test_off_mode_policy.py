"""Unit tests for off-mode persist decisions and job-wire parsing."""

from __future__ import annotations

import pytest
from api.analytics.fleet.types import STAMP_CURRENT_EVIDENCE_MARK, FleetEvidenceMark
from api.analytics.off_mode import MarkPersist, off_mode_persist_decision, parse_off_mode_wire
from api.errors import ValidationError


def test_off_mode_persist_decision_is_one_table():
    """Scoreboard classification and the fleet merge generation share one record."""
    present = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    absent = FleetEvidenceMark()
    cases = (
        (
            "open turn stamps and keeps the stored generation",
            False,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.STAMP,
            1,
        ),
        (
            "open turn with no file keeps generation 0",
            False,
            40,
            False,
            40,
            present,
            None,
            MarkPersist.STAMP,
            0,
        ),
        (
            "catch-up hop merge stamps; a scoreboard of that turn would bump",
            False,
            40,
            True,
            39,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "later turn bumps and stamps the merge",
            False,
            40,
            False,
            41,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "no open turn bumps",
            False,
            None,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark with no open is the first persist",
            False,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark on the open turn is the first persist and keeps 0",
            False,
            40,
            False,
            40,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            0,
        ),
        (
            "backfill on bumps and stamps the merge",
            True,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "backfill on an absent mark is the first persist",
            True,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "catch-up flag on the open turn still stamps the mark and the merge",
            False,
            40,
            True,
            40,
            present,
            1,
            MarkPersist.STAMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
    )
    for (
        name,
        backfill_enabled,
        open_turn,
        is_catch_up,
        host_turn,
        mark,
        stored_generation,
        mark_persist,
        merge_generation,
    ) in cases:
        decision = off_mode_persist_decision(
            backfill_enabled=backfill_enabled,
            open_turn=open_turn,
            is_catch_up=is_catch_up,
            host_turn=host_turn,
            mark=mark,
            stored_generation=stored_generation,
        )
        assert decision.mark_persist is mark_persist, name
        assert decision.merge_generation == merge_generation, name


def test_parse_off_mode_wire_rejects_wrong_types_and_catch_up_without_open_turn():
    """Absent fields stay absent. A present field of the wrong JSON type is rejected."""
    empty = parse_off_mode_wire({})
    assert empty.open_turn is None
    assert empty.catch_up is False
    assert empty.backfill_earlier_turns is None
    assert empty.player_invalidation_generation is None

    parsed = parse_off_mode_wire(
        {
            "openTurn": 40,
            "catchUp": False,
            "backfillEarlierTurns": True,
            "playerInvalidationGeneration": 2,
        }
    )
    assert parsed.open_turn == 40
    assert parsed.catch_up is False
    assert parsed.backfill_earlier_turns is True
    assert parsed.player_invalidation_generation == 2

    for wire in (
        {"openTurn": True},
        {"openTurn": 40, "catchUp": 1},
        {"backfillEarlierTurns": 0},
        {"playerInvalidationGeneration": True},
        {"catchUp": True},
    ):
        with pytest.raises(ValidationError):
            parse_off_mode_wire(wire)
