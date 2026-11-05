"""Submission open: explicit root wins, and a carried backfill choice stays."""

from __future__ import annotations

from api.compute.orchestrator_state import ComputeRequest
from api.compute.orchestrator_submission import resolve_submission_open, submission_open_turn
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


def _request(
    turn: int | str,
    submission_open: SubmissionOpen | None = None,
) -> ComputeRequest:
    return ComputeRequest(
        scope=ComputeScope(
            analytic_id="fleet",
            game_id=1,
            perspective=1,
            turn=turn,
            player_id=7,
        ),
        submission_open=submission_open,
    )


def test_explicit_open_turn_wins_over_the_scope_turn() -> None:
    carried = SubmissionOpen(open_turn=40, backfill_earlier_turns=True)
    request, resolved = resolve_submission_open(_request(39, carried))
    assert resolved == carried
    assert request.submission_open == carried
    assert submission_open_turn(request) == 40


def test_absent_submission_open_uses_the_scope_turn_and_backfill_off() -> None:
    request, resolved = resolve_submission_open(_request(40))
    assert resolved == SubmissionOpen(open_turn=40, backfill_earlier_turns=False)
    assert request.submission_open == resolved


def test_carried_backfill_keeps_its_choice_when_the_open_turn_is_derived() -> None:
    request, resolved = resolve_submission_open(
        _request(39, SubmissionOpen(backfill_earlier_turns=True))
    )
    assert resolved == SubmissionOpen(open_turn=39, backfill_earlier_turns=True)
    assert request.submission_open == resolved
    again, stable = resolve_submission_open(request)
    assert again is request
    assert stable == resolved


def test_scope_without_a_concrete_turn_has_no_open_turn() -> None:
    request, resolved = resolve_submission_open(_request("*"))
    assert resolved == SubmissionOpen(open_turn=None, backfill_earlier_turns=False)
    assert submission_open_turn(request) is None
    boolean_turn = ComputeRequest(
        scope=ComputeScope(
            analytic_id="fleet",
            game_id=1,
            perspective=1,
            turn=True,
            player_id=7,
        )
    )
    _request_again, boolean_resolved = resolve_submission_open(boolean_turn)
    assert boolean_resolved.open_turn is None
    assert submission_open_turn(_request_again) is None
