"""Unit tests for off-mode persist decisions, prior-fleet relation, and job-wire parsing."""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.fleet.types import (
    STAMP_CURRENT_EVIDENCE_MARK,
    FleetAcquisitionLedger,
    FleetEvidenceMark,
    PersistedFleetLedger,
)
from api.analytics.off_mode import (
    MarkPersist,
    PriorFleetRelation,
    off_mode_persist_decision,
    off_mode_prior_needs_catch_up,
    off_mode_prior_relation,
    parse_off_mode_wire,
)
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


def test_off_mode_prior_relation_classifies_stop_hop_and_on_mark(sample_turn):
    """Floor, absent mark, appliesFromTurn, a missing turn, and the mark share one result."""
    stored = sample_turn
    normal = replace(sample_turn.settings, acceleratedturns=0)
    accelerated = replace(sample_turn.settings, acceleratedturns=5)
    absent = FleetEvidenceMark()
    ranged = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)

    def ledger(generation: int) -> PersistedFleetLedger:
        return PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(player_id=1),
            evidence_generation=generation,
        )

    cases = (
        (
            "prior below the accelerated floor",
            5,
            accelerated,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=4),
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "turn 1 has no prior",
            1,
            normal,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=1),
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "first turn at the accelerated floor can hop",
            6,
            accelerated,
            True,
            ledger(1),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=5),
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "absent mark and no ledger",
            40,
            normal,
            True,
            None,
            absent,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "absent mark and a generation-0 ledger on a stored turn",
            40,
            normal,
            True,
            ledger(0),
            absent,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "absent mark and a generation-0 ledger when the turn is not stored",
            40,
            normal,
            False,
            ledger(0),
            absent,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "absent mark and a ledger behind generation 0",
            40,
            normal,
            True,
            ledger(2),
            absent,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "stored ledger before appliesFromTurn is on the mark",
            40,
            normal,
            True,
            ledger(1),
            ranged,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "ledger before appliesFromTurn when the turn is not stored",
            40,
            normal,
            False,
            ledger(1),
            ranged,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "no ledger before appliesFromTurn",
            40,
            normal,
            True,
            None,
            ranged,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "turn not stored inside the mark range",
            41,
            normal,
            False,
            ledger(3),
            ranged,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "stored ledger on the mark",
            41,
            normal,
            True,
            ledger(3),
            ranged,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "stored ledger behind the mark",
            41,
            normal,
            True,
            ledger(1),
            ranged,
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "missing ledger inside the mark range",
            41,
            normal,
            True,
            None,
            ranged,
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "mark with no appliesFromTurn matches its generation",
            41,
            normal,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3),
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "mark with no appliesFromTurn and a ledger behind it",
            41,
            normal,
            True,
            ledger(1),
            FleetEvidenceMark(evidence_generation=3),
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
    )
    for (
        name,
        turn_number,
        settings,
        prior_stored,
        prior_ledger,
        mark,
        expected,
        reads_prior_turn,
    ) in cases:
        loaded = stored if prior_stored else None
        calls: list[int] = []

        def load_prior_turn(loaded=loaded, calls=calls):
            calls.append(1)
            return loaded

        relation = off_mode_prior_relation(
            turn_number=turn_number,
            settings=settings,
            load_prior_turn=load_prior_turn,
            prior_ledger=prior_ledger,
            mark=mark,
        )
        assert relation is expected, name
        assert bool(calls) is reads_prior_turn, name
        assert off_mode_prior_needs_catch_up(
            turn_number=turn_number,
            settings=settings,
            load_turn=lambda _turn_number, loaded=loaded: loaded,
            prior_ledger=prior_ledger,
            mark=mark,
        ) is (expected is PriorFleetRelation.HOP_NEEDED), name


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
