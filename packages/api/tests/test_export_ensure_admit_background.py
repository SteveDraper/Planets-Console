"""Admit export scopes at background without waiting (MCP hatch ensure)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from api.analytics.export_types import ExportScope, ExportScopeOverrides
from api.compute import export_ensure as export_ensure_module
from api.compute.export_ensure import admit_export_scope_at_background


def _ctx_with_scores_catalog(*, resolved_scope: ExportScope) -> MagicMock:
    catalog = MagicMock()
    ctx = MagicMock()
    ctx.export_registry = {"scores": catalog}
    ctx.resolve_scope.return_value = resolved_scope
    return ctx


def test_admit_at_background_returns_already_satisfied_without_submit(monkeypatch):
    scope = ExportScope(game_id=1, perspective=2, turn=3, player_id=8)
    ctx = _ctx_with_scores_catalog(resolved_scope=scope)
    overrides = ExportScopeOverrides(player_id=8)
    monkeypatch.setattr(
        export_ensure_module,
        "export_scope_is_ensure_final",
        lambda *_args, **_kwargs: True,
    )

    with patch("api.compute.runtime.get_compute_orchestrator") as get_orch:
        outcome = admit_export_scope_at_background(ctx, "scores", overrides)

    assert outcome == "already_satisfied"
    ctx.resolve_scope.assert_called_once_with(overrides)
    get_orch.assert_not_called()


def test_admit_at_background_submits_background_and_does_not_wait(monkeypatch):
    scope = ExportScope(game_id=1, perspective=2, turn=3, player_id=8)
    ctx = _ctx_with_scores_catalog(resolved_scope=scope)
    overrides = ExportScopeOverrides(player_id=8)
    compute_scope = MagicMock()
    captured_scope: list[ExportScope] = []
    monkeypatch.setattr(
        export_ensure_module,
        "export_scope_is_ensure_final",
        lambda *_args, **_kwargs: False,
    )

    def _capture_registered(_analytic_id: str, resolved_scope: ExportScope):
        captured_scope.append(resolved_scope)
        return (MagicMock(), compute_scope)

    monkeypatch.setattr(
        export_ensure_module,
        "_registered_compute_scope",
        _capture_registered,
    )
    handle = MagicMock()
    handle.wait.side_effect = AssertionError("admit must not wait")
    orchestrator = MagicMock()
    orchestrator.submit.return_value = handle

    with patch(
        "api.compute.runtime.get_compute_orchestrator",
        return_value=orchestrator,
    ):
        outcome = admit_export_scope_at_background(ctx, "scores", overrides)

    assert outcome == "accepted"
    ctx.resolve_scope.assert_called_once_with(overrides)
    assert captured_scope == [scope]
    request = orchestrator.submit.call_args.args[0]
    assert request.priority_band == "background"
    assert request.force_fresh is False
    assert request.scope is compute_scope
    handle.wait.assert_not_called()


def test_admit_at_background_missing_compute_registry_raises(monkeypatch):
    scope = ExportScope(game_id=1, perspective=2, turn=3, player_id=8)
    catalog = MagicMock()
    ctx = MagicMock()
    ctx.export_registry = {"fixture-no-compute": catalog}
    ctx.resolve_scope.return_value = scope
    overrides = ExportScopeOverrides(player_id=8)
    monkeypatch.setattr(
        export_ensure_module,
        "export_scope_is_ensure_final",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        export_ensure_module,
        "_registered_compute_scope",
        lambda *_args, **_kwargs: None,
    )

    with (
        patch("api.compute.runtime.get_compute_orchestrator") as get_orch,
        pytest.raises(RuntimeError, match="not in COMPUTE_REGISTRY"),
    ):
        admit_export_scope_at_background(ctx, "fixture-no-compute", overrides)

    get_orch.assert_not_called()
