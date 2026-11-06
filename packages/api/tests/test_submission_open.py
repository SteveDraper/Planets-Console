"""Submission open: explicit root wins, and a carried backfill choice stays."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.options import TurnAnalyticsOptions
from api.compute.errors import UnresolvedSubmissionOpenError
from api.compute.orchestrator_state import ComputeRequest, ResolvedComputeRequest
from api.compute.orchestrator_submission import resolve_submission_open, submission_open_turn
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


def _request(
    turn: int | str,
    submission_open: SubmissionOpen | None = None,
    *,
    ctx: AnalyticQueryContext | None = None,
) -> ComputeRequest:
    return ComputeRequest(
        scope=ComputeScope(
            analytic_id="fleet",
            game_id=1,
            perspective=1,
            turn=turn,
            player_id=7,
        ),
        ctx=ctx,
        submission_open=submission_open,
    )


def _ctx(reader: Callable[[int], bool]) -> AnalyticQueryContext:
    return AnalyticQueryContext(
        game_id=1,
        perspective=1,
        ambient_turn=40,
        options=TurnAnalyticsOptions(),
        load_turn=lambda _turn: None,
        export_registry={},
        read_backfill_earlier_turns=reader,
    )


def _open(resolved: ResolvedComputeRequest) -> SubmissionOpen:
    return resolved.submission_open


def test_explicit_open_turn_wins_over_the_scope_turn() -> None:
    carried = SubmissionOpen(open_turn=40, backfill_earlier_turns=True)
    resolved = resolve_submission_open(_request(39, carried))
    assert _open(resolved) == carried
    assert resolved.request.submission_open == carried
    assert submission_open_turn(resolved.request) == 40


def test_absent_submission_open_without_a_bundle_raises() -> None:
    with pytest.raises(UnresolvedSubmissionOpenError, match="no orchestration bundle"):
        resolve_submission_open(_request(40))


def test_absent_submission_open_reads_the_bundle_reader() -> None:
    resolved = resolve_submission_open(_request(40, ctx=_ctx(lambda _game_id: True)))
    assert _open(resolved) == SubmissionOpen(open_turn=40, backfill_earlier_turns=True)
    assert resolved.request.submission_open == _open(resolved)


def test_missing_backfill_reader_raises() -> None:
    ctx = AnalyticQueryContext(
        game_id=1,
        perspective=1,
        ambient_turn=40,
        options=TurnAnalyticsOptions(),
        load_turn=lambda _turn: None,
        export_registry={},
    )
    with pytest.raises(RuntimeError, match="no Backfill earlier turns reader"):
        resolve_submission_open(_request(40, ctx=ctx))


def test_carried_backfill_keeps_its_choice_when_the_open_turn_is_derived() -> None:
    resolved = resolve_submission_open(_request(39, SubmissionOpen(backfill_earlier_turns=True)))
    assert _open(resolved) == SubmissionOpen(open_turn=39, backfill_earlier_turns=True)
    assert resolved.request.submission_open == _open(resolved)
    again = resolve_submission_open(resolved.request)
    assert again.request is resolved.request
    assert _open(again) == _open(resolved)


def test_scope_without_a_concrete_turn_has_no_open_turn() -> None:
    ctx = _ctx(lambda _game_id: False)
    resolved = resolve_submission_open(_request("*", ctx=ctx))
    assert _open(resolved) == SubmissionOpen(open_turn=None, backfill_earlier_turns=False)
    assert submission_open_turn(resolved.request) is None
    boolean_turn = ComputeRequest(
        scope=ComputeScope(
            analytic_id="fleet",
            game_id=1,
            perspective=1,
            turn=True,
            player_id=7,
        ),
        ctx=ctx,
    )
    boolean_resolved = resolve_submission_open(boolean_turn)
    assert _open(boolean_resolved).open_turn is None
    assert submission_open_turn(boolean_resolved.request) is None

    with pytest.raises(UnresolvedSubmissionOpenError, match="no orchestration bundle"):
        resolve_submission_open(_request("*"))
