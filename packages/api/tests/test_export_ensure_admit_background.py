"""Admit export scopes at background without waiting (MCP hatch ensure)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.analytics.export_types import ExportScope
from api.compute import export_ensure as export_ensure_module
from api.compute.export_ensure import admit_export_scope_at_background


def test_admit_at_background_returns_already_satisfied_without_submit(monkeypatch):
    catalog = MagicMock()
    ctx = MagicMock()
    ctx.export_registry = {"scores": catalog}
    scope = ExportScope(game_id=1, perspective=2, turn=3, player_id=8)
    monkeypatch.setattr(
        export_ensure_module,
        "export_scope_is_ensure_final",
        lambda *_args, **_kwargs: True,
    )

    with patch("api.compute.runtime.get_compute_orchestrator") as get_orch:
        outcome = admit_export_scope_at_background(ctx, "scores", scope)

    assert outcome == "already_satisfied"
    get_orch.assert_not_called()


def test_admit_at_background_submits_background_and_does_not_wait(monkeypatch):
    catalog = MagicMock()
    ctx = MagicMock()
    ctx.export_registry = {"scores": catalog}
    scope = ExportScope(game_id=1, perspective=2, turn=3, player_id=8)
    compute_scope = MagicMock()
    monkeypatch.setattr(
        export_ensure_module,
        "export_scope_is_ensure_final",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        export_ensure_module,
        "_registered_compute_scope",
        lambda *_args, **_kwargs: (MagicMock(), compute_scope),
    )
    handle = MagicMock()
    handle.wait.side_effect = AssertionError("admit must not wait")
    orchestrator = MagicMock()
    orchestrator.submit.return_value = handle

    with patch(
        "api.compute.runtime.get_compute_orchestrator",
        return_value=orchestrator,
    ):
        outcome = admit_export_scope_at_background(ctx, "scores", scope)

    assert outcome == "accepted"
    request = orchestrator.submit.call_args.args[0]
    assert request.priority_band == "background"
    assert request.scope is compute_scope
    handle.wait.assert_not_called()
