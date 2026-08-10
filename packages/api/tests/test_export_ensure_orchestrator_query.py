"""Phase 2 (#204): ctx.query ensure routes through orchestrator submit+wait."""

from __future__ import annotations

from unittest.mock import patch

from api.analytics import export_context as export_context_module
from api.analytics.export_types import ExportScopeOverrides
from api.compute import export_ensure as export_ensure_module

from tests.fixtures.export_framework.harness import (
    build_stored_turn_chain,
    first_player_id,
    make_fixture_query_context,
)


def test_ensure_blocked_does_not_submit_orchestrator(sample_turn, monkeypatch):
    """Oversized probe still returns ensure_blocked without submit+wait (H1)."""
    monkeypatch.setattr(export_context_module, "INLINE_ENSURE_MAX_MISSING_STEPS", 0)
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    with patch.object(
        export_ensure_module,
        "ensure_export_scope_via_orchestrator",
        side_effect=AssertionError("ensure_blocked must not submit"),
    ):
        result = ctx.query(
            "export-test-alpha",
            ["$.payload.label"],
            ExportScopeOverrides(turn=2, player_id=player_id),
        )

    assert result.status == "unavailable"
    assert result.reason == "ensure_blocked"


def test_query_registered_analytic_uses_orchestrator_ensure(sample_turn, persistence):
    """Scores query root ensure goes through ensure_export_scope_via_orchestrator."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )

    from tests.scores_exports_helpers import prior_turn_ensure_context

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    ctx, _scope, player_id, _, _ = prior_turn_ensure_context(
        sample_turn,
        persistence,
        scheduler=scheduler,
    )

    calls: list[tuple[str, int]] = []

    def fake_ensure(ctx, analytic_id, scope, **_kwargs):
        calls.append((analytic_id, scope.turn))
        # Admit-only so materialize can run without full durable wait in this unit test.
        from api.analytics.scores.exports import admit_scores_export_work

        return admit_scores_export_work(ctx, scope, overlay_ensure=True)

    with patch.object(
        export_ensure_module,
        "ensure_export_scope_via_orchestrator",
        fake_ensure,
    ):
        result = ctx.query(
            "scores",
            ["$.meta.searchStatus"],
            {"turn": 110, "player_id": player_id},
            force_inline_ensure=True,
        )

    assert calls == [("scores", 110)]
    assert result.status == "ok"


def test_fixture_analytic_keeps_sync_ensure_fallback(sample_turn):
    """Catalogs without compute registration still use sync ensure_export walk."""
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    with patch.object(
        export_ensure_module,
        "ensure_export_scope_via_orchestrator",
        side_effect=AssertionError("fixtures must not use compute ensure"),
    ):
        result = ctx.query(
            "export-test-alpha",
            ["$.payload.label"],
            ExportScopeOverrides(turn=2, player_id=player_id),
            force_inline_ensure=True,
        )

    assert result.status == "ok"
    assert result.paths["$.payload.label"].kind == "value"
