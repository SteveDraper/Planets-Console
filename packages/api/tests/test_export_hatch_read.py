"""Core hatch-read: ensure-final materialize, no new analytic export ensure."""

from __future__ import annotations

from unittest.mock import patch

from api.analytics import export_context as export_context_module
from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope, ExportScopeOverrides
from api.analytics.options import TurnAnalyticsOptions
from api.compute import export_ensure as export_ensure_module

from tests.fixtures.export_framework.harness import (
    build_stored_turn_chain,
    first_player_id,
    make_fixture_query_context,
)
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

ALPHA_PATHS = ["$.payload.label"]


def _alpha_scope(ctx, player_id: int, *, turn: int) -> ExportScope:
    return ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )


def test_hatch_read_missing_persist_is_needs_ensure(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "unavailable"
    assert result.reason == "needs_ensure"
    assert FIXTURE_EXPORT_STATE.ensure_calls == []
    assert FIXTURE_EXPORT_STATE.materialize_calls == []


def test_hatch_read_in_flight_is_in_progress(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    FIXTURE_EXPORT_STATE.mark_in_progress(
        "export-test-alpha",
        _alpha_scope(ctx, player_id, turn=2),
    )

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "unavailable"
    assert result.reason == "in_progress"
    assert FIXTURE_EXPORT_STATE.ensure_calls == []
    assert FIXTURE_EXPORT_STATE.materialize_calls == []


def test_hatch_read_ensure_final_envelope_matches_query(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    scope = ExportScopeOverrides(turn=2, player_id=player_id)

    queried = ctx.query("export-test-alpha", ALPHA_PATHS, scope)
    hatch = ctx.hatch_read("export-test-alpha", ALPHA_PATHS, scope)

    assert queried.status == "ok"
    assert queried.paths["$.payload.label"].kind == "value"
    assert hatch == queried


def test_hatch_read_persisted_fixture_without_query_is_ok(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    FIXTURE_EXPORT_STATE.mark_persisted(
        "export-test-alpha",
        _alpha_scope(ctx, player_id, turn=2),
    )

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "ok"
    assert result.paths["$.payload.label"].kind == "value"
    assert result.paths["$.payload.label"].value == f"alpha-t2-p{player_id}"
    assert FIXTURE_EXPORT_STATE.ensure_calls == []


def test_query_still_admits_ensure_after_hatch_read_needs_ensure(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    scope = ExportScopeOverrides(turn=2, player_id=player_id)

    blocked = ctx.hatch_read("export-test-alpha", ALPHA_PATHS, scope)
    queried = ctx.query("export-test-alpha", ALPHA_PATHS, scope)
    hatch = ctx.hatch_read("export-test-alpha", ALPHA_PATHS, scope)

    assert blocked.reason == "needs_ensure"
    assert queried.status == "ok"
    assert FIXTURE_EXPORT_STATE.ensure_calls
    assert hatch == queried


def test_hatch_read_does_not_submit_orchestrator(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    with patch.object(
        export_ensure_module,
        "ensure_export_scope_via_orchestrator",
        side_effect=AssertionError("hatch_read must not submit ensure"),
    ):
        result = ctx.hatch_read(
            "export-test-alpha",
            ALPHA_PATHS,
            ExportScopeOverrides(turn=2, player_id=player_id),
        )

    assert result.status == "unavailable"
    assert result.reason == "needs_ensure"


def test_hatch_read_does_not_return_ensure_blocked(sample_turn, monkeypatch):
    monkeypatch.setattr(export_context_module, "INLINE_ENSURE_MAX_MISSING_STEPS", 0)
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "unavailable"
    assert result.reason == "needs_ensure"


def test_hatch_read_turn_not_stored(sample_turn):
    player_id = first_player_id(sample_turn)
    ctx = make_fixture_query_context(
        sample_turn,
        stored_turns={sample_turn.settings.turn: sample_turn},
    )

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=sample_turn.settings.turn - 1, player_id=player_id),
    )

    assert result.status == "unavailable"
    assert result.reason == "turn_not_stored"
    assert FIXTURE_EXPORT_STATE.ensure_calls == []


def test_hatch_read_invalid_scope(sample_turn):
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.hatch_read(
        "export-test-alpha",
        ALPHA_PATHS,
        ExportScopeOverrides(turn=2),
    )

    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_hatch_read_connections_empty_catalog_matches_query(sample_turn):
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )

    hatch = ctx.hatch_read("connections", ["$"])
    queried = ctx.query("connections", ["$"])

    assert hatch.status == "unavailable"
    assert hatch.reason == "empty_catalog"
    assert hatch == queried


def test_hatch_read_compute_in_flight_is_in_progress(sample_turn, persistence):
    from api.compute.runtime import get_compute_orchestrator

    from tests.scores_exports_helpers import first_player_id as scores_player_id
    from tests.scores_exports_helpers import scores_query_context

    player_id = scores_player_id(sample_turn)
    ctx = scores_query_context(sample_turn, persistence=persistence)
    orchestrator = get_compute_orchestrator()

    with patch.object(orchestrator, "has_nonterminal_scope_work", return_value=True):
        result = ctx.hatch_read(
            "scores",
            ["$.meta.searchStatus"],
            {"player_id": player_id},
        )

    assert result.status == "unavailable"
    assert result.reason == "in_progress"
